from decimal import Decimal
from unittest.mock import patch

import stripe
from django.contrib.auth import get_user_model
from django.core import mail
from django.db import OperationalError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from payments.models import Adresse, Payment, StripeOrderRefund, StripeWebhookEvent
from payments.refunds import (
    RefundMismatch,
    RefundProviderError,
    request_full_refund,
)
from shop.models import Cart, CartItem, Commande, LigneCommande, OrderReceipt, Produit
from shop.receipts import ensure_order_receipt


RETRIEVE_SESSION = "payments.refunds.stripe.checkout.Session.retrieve"
CREATE_REFUND = "payments.refunds.stripe.Refund.create"
CONSTRUCT_EVENT = "payments.views.stripe.Webhook.construct_event"


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="shop@example.test",
    SITE_BASE_URL="https://example.test",
)
class StripeOrderRefundTests(TestCase):
    def setUp(self):
        self.counter = 0
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            email="refund-staff@example.test",
            password="test-password",
            is_staff=True,
        )
        (
            self.customer,
            self.order,
            self.payment,
            self.line,
            self.cart_item,
            self.receipt,
        ) = self.create_paid_order()

    def create_paid_order(self, *, language_code="fr"):
        self.counter += 1
        suffix = self.counter
        customer = get_user_model().objects.create_user(
            email=f"refund-customer-{suffix}@example.test",
            password="test-password",
            first_name="Ada",
            last_name="Lovelace",
        )
        address = Adresse.objects.create(
            utilisateur=customer,
            rue="1 rue du Remboursement",
            ville="Paris",
            code_postal="75001",
            pays="France",
        )
        product = Produit.objects.create(
            nom=f"Produit remboursable {suffix}",
            slug=f"produit-remboursable-{suffix}",
            prix=Decimal("50.00"),
        )
        cart = Cart.objects.create(user=customer)
        cart_item = CartItem.objects.create(
            cart=cart,
            produit=product,
            quantite=1,
            prix_unitaire=product.prix,
        )
        session_id = f"cs_refund_{suffix}"
        order = Commande.objects.create(
            client=customer,
            adresse=address,
            source_cart=cart,
            total=product.prix,
            currency="EUR",
            language_code=language_code,
            payment_status="SUCCESS",
            payment_channel="STRIPE",
            transaction_id=session_id,
            fulfillment_status="PREPARING",
            cart_finalized_at=timezone.now(),
        )
        line = LigneCommande.objects.create(
            commande=order,
            produit=product,
            source_cart_item=cart_item,
            quantite=1,
            prix_unitaire=product.prix,
        )
        payment = Payment.objects.create(
            commande=order,
            montant=order.total,
            devise=order.currency,
            transaction_id=session_id,
            channel="STRIPE",
            status="SUCCESS",
        )
        receipt = ensure_order_receipt(order)
        return customer, order, payment, line, cart_item, receipt

    def checkout_session(self, payment=None, **overrides):
        payment = payment or self.payment
        session = {
            "id": payment.transaction_id,
            "status": "complete",
            "payment_status": "paid",
            "amount_total": 5000,
            "currency": "eur",
            "payment_intent": f"pi_{payment.id}",
            "metadata": {
                "commande_id": str(payment.commande_id),
                "payment_id": str(payment.id),
                "user_id": str(payment.commande.client_id),
            },
        }
        session.update(overrides)
        return session

    def refund_response(self, create_kwargs, *, status="succeeded", **overrides):
        response = {
            "id": f"re_{create_kwargs['metadata']['refund_request_id']}",
            "status": status,
            "payment_intent": create_kwargs["payment_intent"],
            "amount": create_kwargs["amount"],
            "currency": "eur",
            "metadata": create_kwargs["metadata"],
        }
        response.update(overrides)
        return response

    def provider_mocks(self, payment=None, *, status="succeeded"):
        payment = payment or self.payment

        def create(**kwargs):
            return self.refund_response(kwargs, status=status)

        return (
            patch(
                RETRIEVE_SESSION,
                return_value=self.checkout_session(payment),
            ),
            patch(CREATE_REFUND, side_effect=create),
        )

    def refund_event(
        self,
        refund,
        *,
        event_id="evt_refund",
        status="succeeded",
        **overrides,
    ):
        provider_refund = {
            "id": refund.stripe_refund_id or f"re_{refund.id}",
            "status": status,
            "payment_intent": refund.stripe_payment_intent_id,
            "amount": 5000,
            "currency": "eur",
            "metadata": {
                "refund_request_id": str(refund.id),
                "commande_id": str(refund.commande_id),
                "payment_id": str(refund.payment_id),
                "user_id": str(refund.commande.client_id),
            },
        }
        provider_refund.update(overrides)
        return {
            "id": event_id,
            "type": "refund.updated",
            "data": {"object": provider_refund},
        }

    def test_confirmation_screen_is_staff_only_and_contains_local_summary(self):
        url = reverse(
            "shop:confirmer_remboursement_commande",
            args=[self.order.pk],
        )
        with patch(RETRIEVE_SESSION) as retrieve, patch(CREATE_REFUND) as create:
            self.client.force_login(self.customer)
            self.assertEqual(self.client.get(url).status_code, 302)

            self.client.force_login(self.staff)
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"#{self.order.pk}")
        self.assertContains(response, self.customer.email)
        self.assertContains(response, "50,00 EUR")
        self.assertContains(response, "csrfmiddlewaretoken")
        retrieve.assert_not_called()
        create.assert_not_called()

    def test_refund_action_rejects_get_and_requires_csrf(self):
        url = reverse("shop:rembourser_commande", args=[self.order.pk])
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 405)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        with patch(RETRIEVE_SESSION) as retrieve, patch(CREATE_REFUND) as create:
            response = csrf_client.post(url)

        self.assertEqual(response.status_code, 403)
        retrieve.assert_not_called()
        create.assert_not_called()
        self.assertFalse(StripeOrderRefund.objects.exists())

    def test_non_staff_cannot_refund(self):
        self.client.force_login(self.customer)
        with patch(RETRIEVE_SESSION) as retrieve, patch(CREATE_REFUND) as create:
            response = self.client.post(
                reverse("shop:rembourser_commande", args=[self.order.pk])
            )

        self.assertEqual(response.status_code, 302)
        retrieve.assert_not_called()
        create.assert_not_called()
        self.assertFalse(StripeOrderRefund.objects.exists())

    def test_successful_total_refund_uses_only_server_data_and_stable_key(self):
        self.client.force_login(self.staff)
        session_mock, refund_mock = self.provider_mocks()
        with session_mock as retrieve, refund_mock as create:
            response = self.client.post(
                reverse("shop:rembourser_commande", args=[self.order.pk]),
                {
                    "amount": "1",
                    "currency": "usd",
                    "payment_intent": "pi_browser_attack",
                    "payment_id": "999999",
                },
            )

        self.assertEqual(response.status_code, 302)
        refund = StripeOrderRefund.objects.get(commande=self.order)
        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        retrieve.assert_called_once_with(self.payment.transaction_id)
        self.assertEqual(
            create.call_args.kwargs["payment_intent"],
            f"pi_{self.payment.id}",
        )
        self.assertEqual(create.call_args.kwargs["amount"], 5000)
        self.assertEqual(
            create.call_args.kwargs["idempotency_key"],
            str(refund.idempotency_key),
        )
        self.assertEqual(refund.status, "SUCCESS")
        self.assertIsNotNone(refund.confirmed_at)
        self.assertEqual(self.order.payment_status, "REFUNDED")
        self.assertEqual(self.payment.status, "SUCCESS")

    def test_refund_preserves_receipt_lines_cart_and_fulfillment(self):
        original_receipt = (self.receipt.pk, self.receipt.public_id)
        session_mock, refund_mock = self.provider_mocks()
        with session_mock, refund_mock:
            request_full_refund(self.order.pk, self.staff.pk)

        self.order.refresh_from_db()
        self.receipt.refresh_from_db()
        self.assertEqual((self.receipt.pk, self.receipt.public_id), original_receipt)
        self.assertTrue(LigneCommande.objects.filter(pk=self.line.pk).exists())
        self.assertTrue(CartItem.objects.filter(pk=self.cart_item.pk).exists())
        self.assertEqual(self.order.fulfillment_status, "PREPARING")

    def test_double_click_creates_one_pending_refund_and_one_provider_call(self):
        self.client.force_login(self.staff)
        session_mock, refund_mock = self.provider_mocks(status="pending")
        with session_mock as retrieve, refund_mock as create:
            first = self.client.post(
                reverse("shop:rembourser_commande", args=[self.order.pk])
            )
            second = self.client.post(
                reverse("shop:rembourser_commande", args=[self.order.pk])
            )

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(StripeOrderRefund.objects.count(), 1)
        self.assertEqual(StripeOrderRefund.objects.get().status, "PENDING")
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "SUCCESS")
        retrieve.assert_called_once()
        create.assert_called_once()

    def test_network_retry_reuses_the_same_idempotency_key(self):
        error = stripe.APIConnectionError("private provider response")
        with patch(RETRIEVE_SESSION, side_effect=error), patch(CREATE_REFUND) as create:
            with self.assertRaises(RefundProviderError):
                request_full_refund(self.order.pk, self.staff.pk)
        create.assert_not_called()
        refund = StripeOrderRefund.objects.get()
        original_key = refund.idempotency_key
        self.assertEqual(refund.status, "RETRYABLE")

        session_mock, refund_mock = self.provider_mocks()
        with session_mock, refund_mock as create:
            request_full_refund(self.order.pk, self.staff.pk)

        refund.refresh_from_db()
        self.assertEqual(refund.idempotency_key, original_key)
        self.assertEqual(create.call_args.kwargs["idempotency_key"], str(original_key))
        self.assertEqual(refund.status, "SUCCESS")

    def test_checkout_amount_currency_and_metadata_mismatches_are_rejected(self):
        cases = (
            {"amount_total": 4999},
            {"currency": "usd"},
            {"metadata": {"commande_id": "999999"}},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                (
                    _customer,
                    order,
                    payment,
                    _line,
                    _item,
                    _receipt,
                ) = self.create_paid_order()
                with patch(
                    RETRIEVE_SESSION,
                    return_value=self.checkout_session(payment, **overrides),
                ), patch(CREATE_REFUND) as create:
                    with self.assertRaises(RefundMismatch):
                        request_full_refund(order.pk, self.staff.pk)
                create.assert_not_called()
                order.refresh_from_db()
                self.assertEqual(order.payment_status, "SUCCESS")
                self.assertEqual(order.stripe_refund.status, "FAILED")

    def test_checkout_must_be_complete_and_paid(self):
        cases = (
            {"status": "open"},
            {"status": "expired"},
            {"payment_status": "unpaid"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                (
                    _customer,
                    order,
                    payment,
                    _line,
                    _item,
                    _receipt,
                ) = self.create_paid_order()
                with patch(
                    RETRIEVE_SESSION,
                    return_value=self.checkout_session(payment, **overrides),
                ), patch(CREATE_REFUND) as create:
                    with self.assertRaises(RefundMismatch):
                        request_full_refund(order.pk, self.staff.pk)
                create.assert_not_called()
                order.refresh_from_db()
                self.assertEqual(order.payment_status, "SUCCESS")
                self.assertEqual(order.stripe_refund.status, "FAILED")

    def test_provider_refund_amount_and_currency_mismatches_are_rejected(self):
        for overrides in ({"amount": 4999}, {"currency": "usd"}):
            with self.subTest(overrides=overrides):
                _customer, order, payment, _line, _item, _receipt = self.create_paid_order()

                def create(**kwargs):
                    return self.refund_response(kwargs, **overrides)

                with patch(
                    RETRIEVE_SESSION,
                    return_value=self.checkout_session(payment),
                ), patch(CREATE_REFUND, side_effect=create):
                    with self.assertRaises(RefundMismatch):
                        request_full_refund(order.pk, self.staff.pk)
                order.refresh_from_db()
                self.assertEqual(order.payment_status, "SUCCESS")
                self.assertEqual(order.stripe_refund.status, "FAILED")

    def test_non_stripe_and_unpaid_orders_never_call_stripe(self):
        cases = (
            {"payment_channel": "CINETPAY"},
            {"payment_status": "PROCESSING"},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                _customer, order, _payment, _line, _item, _receipt = self.create_paid_order()
                Commande.objects.filter(pk=order.pk).update(**changes)
                with patch(RETRIEVE_SESSION) as retrieve, patch(CREATE_REFUND) as create:
                    self.client.force_login(self.staff)
                    self.client.post(
                        reverse("shop:rembourser_commande", args=[order.pk])
                    )
                retrieve.assert_not_called()
                create.assert_not_called()
                self.assertFalse(
                    StripeOrderRefund.objects.filter(commande=order).exists()
                )

        _customer, order, payment, _line, _item, _receipt = (
            self.create_paid_order()
        )
        payment.channel = "CINETPAY"
        payment.save(update_fields=["channel"])
        with patch(RETRIEVE_SESSION) as retrieve, patch(CREATE_REFUND) as create:
            self.client.post(
                reverse("shop:rembourser_commande", args=[order.pk])
            )
        retrieve.assert_not_called()
        create.assert_not_called()
        self.assertFalse(
            StripeOrderRefund.objects.filter(commande=order).exists()
        )

    def test_browser_cannot_cross_refund_two_orders(self):
        (
            _customer,
            other_order,
            other_payment,
            _line,
            _item,
            _receipt,
        ) = self.create_paid_order()
        self.client.force_login(self.staff)
        session_mock, refund_mock = self.provider_mocks()
        with session_mock, refund_mock:
            self.client.post(
                reverse("shop:rembourser_commande", args=[self.order.pk]),
                {
                    "order_id": str(other_order.pk),
                    "payment_id": str(other_payment.pk),
                },
            )

        self.order.refresh_from_db()
        other_order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "REFUNDED")
        self.assertEqual(other_order.payment_status, "SUCCESS")
        self.assertFalse(
            StripeOrderRefund.objects.filter(commande=other_order).exists()
        )

    def test_pending_refund_webhook_is_idempotent_and_notifies_once(self):
        session_mock, refund_mock = self.provider_mocks(status="pending")
        with session_mock, refund_mock:
            refund = request_full_refund(self.order.pk, self.staff.pk)
        event = self.refund_event(refund)

        with patch(CONSTRUCT_EVENT, return_value=event), self.captureOnCommitCallbacks(
            execute=True
        ):
            first = self.client.post(
                reverse("payments:stripe_webhook"),
                data=b"{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="test-signature",
            )
            second = self.client.post(
                reverse("payments:stripe_webhook"),
                data=b"{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="test-signature",
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        refund.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(refund.status, "SUCCESS")
        self.assertEqual(self.order.payment_status, "REFUNDED")
        self.assertEqual(
            StripeWebhookEvent.objects.filter(
                stripe_event_id="evt_refund"
            ).count(),
            1,
        )
        self.assertEqual(len(mail.outbox), 1)

    def test_notification_uses_the_order_language(self):
        customer, order, payment, _line, _item, _receipt = (
            self.create_paid_order(language_code="de")
        )
        session_mock, refund_mock = self.provider_mocks(payment)
        with self.captureOnCommitCallbacks(execute=True):
            with session_mock, refund_mock:
                request_full_refund(order.pk, self.staff.pk)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [customer.email])
        self.assertIn("Ihre Bestellung", mail.outbox[0].subject)
        self.assertIn("wurde erstattet", mail.outbox[0].subject)

    def test_webhook_mismatch_and_order_isolation_do_not_change_orders(self):
        session_mock, refund_mock = self.provider_mocks(status="pending")
        with session_mock, refund_mock:
            refund = request_full_refund(self.order.pk, self.staff.pk)
        _customer, other_order, _payment, _line, _item, _receipt = self.create_paid_order()
        event = self.refund_event(refund, amount=4999)
        event["data"]["object"]["metadata"]["commande_id"] = str(other_order.pk)

        with patch(CONSTRUCT_EVENT, return_value=event):
            response = self.client.post(
                reverse("payments:stripe_webhook"),
                data=b"{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="test-signature",
            )

        self.assertEqual(response.status_code, 400)
        refund.refresh_from_db()
        self.order.refresh_from_db()
        other_order.refresh_from_db()
        self.assertEqual(refund.status, "PENDING")
        self.assertEqual(self.order.payment_status, "SUCCESS")
        self.assertEqual(other_order.payment_status, "SUCCESS")
        self.assertFalse(StripeWebhookEvent.objects.exists())

    def test_refund_blocks_fulfillment_but_keeps_receipt_downloadable(self):
        session_mock, refund_mock = self.provider_mocks()
        with session_mock, refund_mock:
            request_full_refund(self.order.pk, self.staff.pk)

        self.client.force_login(self.staff)
        self.client.post(
            reverse("shop:commande_traitement_modifier", args=[self.order.pk]),
            {"statut": "SHIPPED", "carrier": "DHL", "tracking_number": "NEW"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, "PREPARING")

        self.client.force_login(self.customer)
        with patch(
            "shop.customer_views.render_order_receipt_pdf",
            return_value=b"%PDF-refund",
        ):
            response = self.client.get(
                reverse(
                    "shop:telecharger_recu_commande",
                    args=[self.order.pk, self.receipt.public_id],
                )
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(OrderReceipt.objects.filter(pk=self.receipt.pk).exists())

    def test_staff_and_customer_details_display_refund(self):
        session_mock, refund_mock = self.provider_mocks()
        with session_mock, refund_mock:
            request_full_refund(self.order.pk, self.staff.pk)

        self.client.force_login(self.staff)
        staff_response = self.client.get(
            reverse("shop:commande_gestion_detail", args=[self.order.pk])
        )
        self.assertContains(staff_response, "Remboursement Stripe")
        self.assertContains(staff_response, "Remboursé")

        self.client.force_login(self.customer)
        customer_response = self.client.get(
            reverse("shop:ma_commande_detail", args=[self.order.pk])
        )
        self.assertContains(customer_response, "Remboursement")
        self.assertContains(customer_response, "Remboursé")
        self.assertContains(customer_response, "Télécharger le reçu PDF")

    def test_programming_and_database_errors_are_not_converted(self):
        with patch(RETRIEVE_SESSION, return_value=self.checkout_session()), patch(
            CREATE_REFUND,
            side_effect=RuntimeError("programming error"),
        ):
            with self.assertRaises(RuntimeError):
                request_full_refund(self.order.pk, self.staff.pk)

        _customer, order, _payment, _line, _item, _receipt = self.create_paid_order()
        with patch.object(
            Payment.objects,
            "select_for_update",
            side_effect=OperationalError("database error"),
        ):
            with self.assertRaises(OperationalError):
                request_full_refund(order.pk, self.staff.pk)
