from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from payments.cancellations import (
    OrderCancellationNotAllowed,
    PaidOrderCancellationNotAllowed,
    cancel_order,
)
from payments.models import Payment
from payments.views import _confirm_payment_once
from shop.inventory import reserve_order_stock
from shop.models import Commande, LigneCommande, OrderCancellation, Produit, StockMovement
from shop.services import SQLiteLockRetryExhausted, execute_with_sqlite_lock_retry


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="shop@example.test",
    SITE_BASE_URL="https://example.test",
)
class OrderCancellationIntegrityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.staff = user_model.objects.create_user(
            email="cancellation-staff@example.test",
            password="test-password",
            is_staff=True,
        )
        cls.customer = user_model.objects.create_user(
            email="cancellation-customer@example.test",
            password="test-password",
            first_name="Anna",
        )
        cls.other_customer = user_model.objects.create_user(
            email="other-cancellation@example.test",
            password="test-password",
        )

    def create_order(
        self,
        *,
        suffix,
        reserve=False,
        payment_channel=None,
        payment_reference=None,
        payment_status="PENDING",
        fulfillment_status="WAITING_PAYMENT",
        language_code="fr",
    ):
        product = Produit.objects.create(
            nom=f"Produit annulation {suffix}",
            slug=f"produit-annulation-{suffix}",
            prix=Decimal("10.00"),
            stock=5,
        )
        order = Commande.objects.create(
            client=self.customer,
            total=Decimal("20.00"),
            payment_status=payment_status,
            payment_channel=payment_channel,
            transaction_id=payment_reference,
            fulfillment_status=fulfillment_status,
            language_code=language_code,
        )
        line = LigneCommande.objects.create(
            commande=order,
            produit=product,
            quantite=2,
            prix_unitaire=product.prix,
        )
        if reserve:
            reserve_order_stock(order.pk)
        payment = None
        if payment_channel:
            payment = Payment.objects.create(
                commande=order,
                montant=order.total,
                devise=order.currency,
                transaction_id=payment_reference,
                channel=payment_channel,
                status=("SUCCESS" if payment_status == "SUCCESS" else "PROCESSING"),
            )
            if payment_status != "SUCCESS":
                order.payment_status = "PROCESSING"
                order.save(update_fields=["payment_status"])
        return order, line, product, payment

    def test_unpaid_order_without_reservation_is_canceled_and_preserved(self):
        order, line, _product, _payment = self.create_order(suffix="plain")
        with self.captureOnCommitCallbacks(execute=True):
            outcome = cancel_order(order.pk, self.customer, "CUSTOMER")

        order.refresh_from_db()
        self.assertTrue(outcome.created)
        self.assertEqual(order.payment_status, "CANCELED")
        self.assertEqual(order.fulfillment_status, "CANCELED")
        self.assertEqual(order.inventory_status, "NONE")
        self.assertTrue(LigneCommande.objects.filter(pk=line.pk).exists())
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_active_reservation_is_released_once_and_audited(self):
        order, line, product, _payment = self.create_order(
            suffix="reserved", reserve=True
        )
        product.refresh_from_db()
        self.assertEqual(product.stock, 3)

        cancel_order(order.pk, self.staff, "STAFF")
        cancel_order(order.pk, self.staff, "STAFF")

        product.refresh_from_db()
        order.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(product.stock, 5)
        self.assertEqual(order.inventory_status, "RELEASED")
        self.assertEqual(line.stock_reserved_quantity, 0)
        releases = StockMovement.objects.filter(
            commande=order,
            movement_type="RELEASE",
        )
        self.assertEqual(releases.count(), 1)
        release = releases.get()
        self.assertEqual(
            (release.stock_before, release.quantity, release.stock_after),
            (3, 2, 5),
        )
        self.assertEqual(OrderCancellation.objects.filter(commande=order).count(), 1)

    def test_open_stripe_session_is_expired_once_with_durable_key(self):
        order, _line, _product, payment = self.create_order(
            suffix="stripe-open",
            reserve=True,
            payment_channel="STRIPE",
            payment_reference="cs_cancel_open",
        )
        with patch(
            "payments.cancellations.stripe.checkout.Session.expire",
            return_value={"status": "expired", "secret": "must-not-be-stored"},
        ) as expire:
            first = cancel_order(order.pk, self.staff, "STAFF")
            second = cancel_order(order.pk, self.staff, "STAFF")

        cancellation = first.cancellation
        cancellation.refresh_from_db()
        payment.refresh_from_db()
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(cancellation.stripe_expiration_status, "SUCCEEDED")
        self.assertIsNotNone(cancellation.stripe_expiration_attempted_at)
        expire.assert_called_once_with(
            payment.transaction_id,
            idempotency_key=str(cancellation.idempotency_key),
        )
        self.assertEqual(payment.status, "CANCELED")
        self.assertIsNone(payment.raw_response)
        self.assertNotIn("secret", str(cancellation.__dict__))

    def test_stripe_expiration_failure_is_controlled_and_local_cancel_remains(self):
        order, _line, product, _payment = self.create_order(
            suffix="stripe-failure",
            reserve=True,
            payment_channel="STRIPE",
            payment_reference="cs_cancel_failure",
        )
        with patch(
            "payments.cancellations.stripe.checkout.Session.expire",
            side_effect=RuntimeError("sensitive-provider-message"),
        ):
            outcome = cancel_order(order.pk, self.staff, "STAFF")

        order.refresh_from_db()
        product.refresh_from_db()
        outcome.cancellation.refresh_from_db()
        self.assertEqual(order.payment_status, "CANCELED")
        self.assertEqual(product.stock, 5)
        self.assertEqual(
            outcome.cancellation.stripe_expiration_status,
            "FAILED",
        )

    def test_late_stripe_webhook_cannot_reopen_or_decrement_canceled_order(self):
        order, _line, product, payment = self.create_order(
            suffix="late-stripe",
            reserve=True,
            payment_channel="STRIPE",
            payment_reference="cs_cancel_late",
        )
        with patch(
            "payments.cancellations.stripe.checkout.Session.expire",
            return_value={"status": "expired"},
        ):
            cancel_order(order.pk, self.staff, "STAFF")

        event = {
            "id": "evt_late_cancellation",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": payment.transaction_id,
                    "status": "complete",
                    "payment_status": "paid",
                    "amount_total": 2000,
                    "currency": "eur",
                    "metadata": {
                        "commande_id": str(order.pk),
                        "payment_id": str(payment.pk),
                        "user_id": str(self.customer.pk),
                    },
                }
            },
        }
        with patch(
            "payments.views.stripe.Webhook.construct_event",
            return_value=event,
        ):
            response = self.client.post(
                reverse("payments:stripe_webhook"),
                data=b"{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="signature",
            )

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        product.refresh_from_db()
        payment.refresh_from_db()
        cancellation = OrderCancellation.objects.get(commande=order)
        self.assertEqual(order.payment_status, "CANCELED")
        self.assertEqual(order.fulfillment_status, "CANCELED")
        self.assertEqual(payment.status, "CANCELED")
        self.assertIsNotNone(cancellation.late_payment_detected_at)
        self.assertEqual(product.stock, 5)
        self.assertEqual(
            StockMovement.objects.filter(
                commande=order, movement_type="RELEASE"
            ).count(),
            1,
        )
        self.assertFalse(
            StockMovement.objects.filter(commande=order, movement_type="SALE").exists()
        )

    def test_late_cinetpay_webhook_records_verified_payment_alert(self):
        order, _line, product, payment = self.create_order(
            suffix="late-cinetpay",
            reserve=True,
            payment_channel="CINETPAY",
            payment_reference="cinetpay_cancel_late",
        )
        cancel_order(order.pk, self.staff, "STAFF")
        with patch(
            "payments.views._cinetpay_check_status",
            return_value={
                "status": "ACCEPTED",
                "amount": str(payment.montant),
                "currency": payment.devise,
            },
        ) as check_status:
            response = self.client.post(
                reverse("payments:cinetpay_ipn"),
                {"transaction_id": payment.transaction_id},
            )
        self.assertEqual(response.status_code, 200)
        check_status.assert_called_once_with(payment.transaction_id)
        product.refresh_from_db()
        self.assertEqual(product.stock, 5)
        self.assertIsNotNone(
            OrderCancellation.objects.get(commande=order).late_payment_detected_at
        )

    def test_paid_order_is_refused_and_staff_confirmation_points_to_refund(self):
        order, _line, product, _payment = self.create_order(
            suffix="paid",
            reserve=True,
            payment_channel="STRIPE",
            payment_reference="cs_cancel_paid",
            payment_status="SUCCESS",
            fulfillment_status="TO_PREPARE",
        )
        with self.assertRaises(PaidOrderCancellationNotAllowed):
            cancel_order(order.pk, self.staff, "STAFF")
        product.refresh_from_db()
        self.assertEqual(product.stock, 3)
        self.assertFalse(OrderCancellation.objects.filter(commande=order).exists())

        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("shop:confirmer_annulation_staff", args=[order.pk])
        )
        self.assertContains(response, "remboursement sécurisé")
        self.assertContains(
            response,
            reverse("shop:confirmer_remboursement_commande", args=[order.pk]),
        )

    def test_shipped_delivered_and_refunded_orders_are_refused(self):
        cases = (
            ("shipped", "PENDING", "SHIPPED"),
            ("delivered", "PENDING", "DELIVERED"),
            ("refunded", "REFUNDED", "CANCELED"),
        )
        for suffix, payment_status, fulfillment_status in cases:
            with self.subTest(suffix=suffix):
                order, _line, _product, _payment = self.create_order(
                    suffix=suffix,
                    payment_status=payment_status,
                    fulfillment_status=fulfillment_status,
                )
                with self.assertRaises(OrderCancellationNotAllowed):
                    cancel_order(order.pk, self.staff, "STAFF")

    def test_permissions_post_only_csrf_and_confirmation(self):
        order, _line, _product, _payment = self.create_order(suffix="security")
        staff_post = reverse("shop:annuler_commande_staff", args=[order.pk])
        customer_post = reverse("shop:annuler_commande_client", args=[order.pk])

        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(staff_post).status_code, 405)
        confirmation = self.client.get(
            reverse("shop:confirmer_annulation_staff", args=[order.pk])
        )
        self.assertContains(confirmation, "Confirmer l’annulation")
        self.assertContains(confirmation, "csrfmiddlewaretoken")

        self.client.force_login(self.customer)
        self.assertEqual(self.client.post(staff_post).status_code, 302)
        self.client.force_login(self.other_customer)
        self.assertEqual(self.client.post(customer_post).status_code, 404)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.customer)
        self.assertEqual(csrf_client.post(customer_post).status_code, 403)

        with self.assertRaises(PermissionDenied):
            cancel_order(order.pk, self.other_customer, "CUSTOMER")

    def test_staff_and_customer_interfaces_show_cancellation(self):
        order, _line, _product, _payment = self.create_order(suffix="display")
        cancel_order(order.pk, self.customer, "CUSTOMER")

        self.client.force_login(self.staff)
        staff_detail = self.client.get(
            reverse("shop:commande_gestion_detail", args=[order.pk])
        )
        self.assertContains(staff_detail, "Commande annulée")

        self.client.force_login(self.customer)
        customer_detail = self.client.get(
            reverse("shop:ma_commande_detail", args=[order.pk])
        )
        customer_list = self.client.get(reverse("shop:mes_commandes"))
        self.assertContains(customer_detail, "Commande annulée")
        self.assertContains(customer_list, "Commande annulée le")

    def test_notification_uses_recorded_order_language_and_is_sent_once(self):
        expected_subjects = {
            "en": "Your order #",
            "de": "Ihre Bestellung Nr.",
        }
        for language_code, expected in expected_subjects.items():
            with self.subTest(language=language_code):
                order, _line, _product, _payment = self.create_order(
                    suffix=f"mail-{language_code}",
                    language_code=language_code,
                )
                with self.captureOnCommitCallbacks(execute=True):
                    first = cancel_order(order.pk, self.customer, "CUSTOMER")
                    second = cancel_order(order.pk, self.customer, "CUSTOMER")
                self.assertTrue(first.created)
                self.assertFalse(second.created)
                self.assertIn(expected, mail.outbox[-1].subject)
                self.assertEqual(mail.outbox[-1].to, [self.customer.email])
                first.cancellation.refresh_from_db()
                self.assertIsNotNone(first.cancellation.notification_sent_at)
        self.assertEqual(len(mail.outbox), 2)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="shop@example.test",
)
class CancellationPaymentRaceTests(TransactionTestCase):
    reset_sequences = True

    def test_cancellation_and_confirmation_finish_in_one_coherent_state(self):
        staff = get_user_model().objects.create_user(
            email="race-cancel-staff@example.test", is_staff=True
        )
        customer = get_user_model().objects.create_user(
            email="race-cancel-customer@example.test"
        )
        product = Produit.objects.create(
            nom="Produit course annulation",
            slug="produit-course-annulation",
            prix=Decimal("10.00"),
            stock=1,
        )
        order = Commande.objects.create(
            client=customer,
            total=Decimal("10.00"),
            payment_status="PROCESSING",
            payment_channel="STRIPE",
            transaction_id="pending_cancel_race",
        )
        LigneCommande.objects.create(
            commande=order,
            produit=product,
            quantite=1,
            prix_unitaire=product.prix,
        )
        reserve_order_stock(order.pk)
        payment = Payment.objects.create(
            commande=order,
            montant=order.total,
            devise=order.currency,
            transaction_id=order.transaction_id,
            channel="STRIPE",
            status="PROCESSING",
        )
        barrier = Barrier(2)

        def cancel():
            close_old_connections()
            barrier.wait()
            try:
                execute_with_sqlite_lock_retry(
                    lambda: cancel_order(order.pk, staff, "STAFF"),
                    attempts=10,
                    base_delay=0.01,
                )
            except (PaidOrderCancellationNotAllowed, SQLiteLockRetryExhausted):
                pass
            close_old_connections()

        def confirm():
            close_old_connections()
            barrier.wait()
            try:
                execute_with_sqlite_lock_retry(
                    lambda: _confirm_payment_once(payment.pk, {"safe": "record"}),
                    attempts=10,
                    base_delay=0.01,
                )
            except SQLiteLockRetryExhausted:
                pass
            close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(cancel), executor.submit(confirm)]
            for future in futures:
                future.result()

        order.refresh_from_db()
        product.refresh_from_db()
        payment.refresh_from_db()
        if order.payment_status == "CANCELED":
            self.assertEqual(order.fulfillment_status, "CANCELED")
            self.assertEqual(payment.status, "CANCELED")
            self.assertEqual(product.stock, 1)
            self.assertEqual(
                StockMovement.objects.filter(
                    commande=order, movement_type="RELEASE"
                ).count(),
                1,
            )
        else:
            self.assertEqual(order.payment_status, "SUCCESS")
            self.assertEqual(payment.status, "SUCCESS")
            self.assertEqual(product.stock, 0)
            self.assertFalse(OrderCancellation.objects.filter(commande=order).exists())
