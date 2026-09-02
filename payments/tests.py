import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from payments.models import Adresse, Payment
from shop.models import Cart, CartItem, Commande, LigneCommande, Produit


class OrderPaymentSecurityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="payer@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.product = Produit.objects.create(
            nom="Produit paiement",
            slug="produit-paiement",
            prix=Decimal("10.00"),
        )
        self.cart = Cart.objects.create(user=self.user)
        self.item = CartItem.objects.create(
            cart=self.cart,
            produit=self.product,
            quantite=2,
            prix_unitaire=self.product.prix,
        )
        self.address = Adresse.objects.create(
            utilisateur=self.user,
            rue="1 rue du Paiement",
            ville="Paris",
            code_postal="75001",
            pays="France",
        )
        self.order = Commande.objects.create(
            client=self.user,
            adresse=self.address,
            source_cart=self.cart,
            total=Decimal("20.00"),
            currency="EUR",
        )
        LigneCommande.objects.create(
            commande=self.order,
            produit=self.product,
            source_cart_item=self.item,
            quantite=2,
            prix_unitaire=self.product.prix,
        )

    def stripe_session(self, session_id="cs_test_order"):
        return SimpleNamespace(id=session_id, url="https://stripe.test/checkout")

    def stripe_event(self, payment, **overrides):
        session = {
            "id": payment.transaction_id,
            "payment_status": "paid",
            "amount_total": 2000,
            "currency": "eur",
            "metadata": {
                "commande_id": str(self.order.id),
                "user_id": str(self.user.id),
                "payment_id": str(payment.id),
            },
        }
        session.update(overrides)
        return {"type": "checkout.session.completed", "data": {"object": session}}

    def initiate_stripe(self):
        with patch(
            "payments.views.stripe.checkout.Session.create",
            return_value=self.stripe_session(),
        ) as create:
            response = self.client.post(
                reverse("payments:stripe_checkout", args=[self.order.id])
            )
        return response, create

    def test_stripe_initialization_is_idempotent(self):
        first_response, first_create = self.initiate_stripe()
        second_response, second_create = self.initiate_stripe()

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(first_response.url, second_response.url)
        self.assertEqual(first_create.call_count, 1)
        self.assertEqual(second_create.call_count, 0)
        self.assertEqual(Payment.objects.filter(status="PROCESSING").count(), 1)
        payment = Payment.objects.get()
        self.assertEqual(payment.transaction_id, "cs_test_order")
        self.assertEqual(
            first_create.call_args.kwargs["idempotency_key"],
            str(payment.idempotency_key),
        )

    def test_active_stripe_payment_blocks_cinetpay(self):
        self.initiate_stripe()

        with patch("payments.views.requests.post") as post:
            response = self.client.post(
                reverse("payments:cinetpay_create", args=[self.order.id])
            )

        self.assertEqual(response.status_code, 409)
        post.assert_not_called()
        self.assertEqual(Payment.objects.count(), 1)

    def test_cinetpay_initialization_is_idempotent(self):
        provider_response = Mock()
        provider_response.json.return_value = {
            "code": "201",
            "data": {"payment_url": "https://cinetpay.test/checkout"},
        }
        with patch("payments.views.requests.post", return_value=provider_response) as post:
            first = self.client.post(
                reverse("payments:cinetpay_create", args=[self.order.id])
            )
            second = self.client.post(
                reverse("payments:cinetpay_create", args=[self.order.id])
            )

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(first.url, second.url)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(Payment.objects.filter(status="PROCESSING").count(), 1)

    def test_valid_stripe_webhook_is_idempotent(self):
        self.initiate_stripe()
        payment = Payment.objects.get()
        event = self.stripe_event(payment)

        with patch("payments.views.stripe.Webhook.construct_event", return_value=event):
            first = self.client.post(
                reverse("payments:stripe_webhook"),
                data=b"{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="signature",
            )
            second = self.client.post(
                reverse("payments:stripe_webhook"),
                data=b"{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="signature",
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(payment.status, "SUCCESS")
        self.assertEqual(self.order.payment_status, "SUCCESS")
        self.assertFalse(CartItem.objects.filter(pk=self.item.pk).exists())

    def test_stripe_webhook_rejects_wrong_amount_currency_status_or_session(self):
        invalid_values = (
            {"amount_total": 1999},
            {"currency": "usd"},
            {"payment_status": "unpaid"},
            {"id": "cs_old_session"},
        )
        for overrides in invalid_values:
            with self.subTest(overrides=overrides):
                self.order.payment_status = "PENDING"
                self.order.transaction_id = None
                self.order.cart_finalized_at = None
                self.order.save(update_fields=[
                    "payment_status", "transaction_id", "cart_finalized_at"
                ])
                Payment.objects.all().delete()
                self.initiate_stripe()
                payment = Payment.objects.get()
                event = self.stripe_event(payment, **overrides)
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
                self.assertEqual(response.status_code, 400)
                payment.refresh_from_db()
                self.assertEqual(payment.status, "PROCESSING")

    def test_valid_cinetpay_callback_is_idempotent(self):
        provider_response = Mock()
        provider_response.json.return_value = {
            "code": "201",
            "data": {"payment_url": "https://cinetpay.test/checkout"},
        }
        with patch("payments.views.requests.post", return_value=provider_response):
            self.client.post(reverse("payments:cinetpay_create", args=[self.order.id]))
        payment = Payment.objects.get()
        provider_data = {
            "status": "ACCEPTED",
            "amount": "20.00",
            "currency": "EUR",
        }

        with patch(
            "payments.views._cinetpay_check_status",
            return_value=provider_data,
        ):
            first = self.client.post(
                reverse("payments:cinetpay_ipn"),
                data=json.dumps({"transaction_id": payment.transaction_id}),
                content_type="application/json",
            )
            second = self.client.post(
                reverse("payments:cinetpay_ipn"),
                data=json.dumps({"transaction_id": payment.transaction_id}),
                content_type="application/json",
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(payment.status, "SUCCESS")
        self.assertEqual(self.order.payment_status, "SUCCESS")

    def test_cinetpay_callback_rejects_old_reference_or_wrong_amount(self):
        Payment.objects.create(
            commande=self.order,
            montant=self.order.total,
            devise=self.order.currency,
            transaction_id="expected-transaction",
            channel="CINETPAY",
            status="PROCESSING",
        )
        self.order.payment_status = "PROCESSING"
        self.order.payment_channel = "CINETPAY"
        self.order.transaction_id = "expected-transaction"
        self.order.save(update_fields=[
            "payment_status", "payment_channel", "transaction_id"
        ])

        provider_data = {
            "status": "ACCEPTED",
            "amount": "19.00",
            "currency": "EUR",
        }
        with patch(
            "payments.views._cinetpay_check_status",
            return_value=provider_data,
        ):
            response = self.client.post(
                reverse("payments:cinetpay_ipn"),
                data=json.dumps({"transaction_id": "expected-transaction"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "PROCESSING")

        old_callback = self.client.post(
            reverse("payments:cinetpay_ipn"),
            data={"cpm_trans_id": "old-transaction"},
        )
        self.assertEqual(old_callback.status_code, 404)

    def test_confirmed_cinetpay_refusal_closes_active_payment(self):
        payment = Payment.objects.create(
            commande=self.order,
            montant=self.order.total,
            devise=self.order.currency,
            transaction_id="refused-transaction",
            channel="CINETPAY",
            status="PROCESSING",
        )
        self.order.payment_status = "PROCESSING"
        self.order.payment_channel = "CINETPAY"
        self.order.transaction_id = payment.transaction_id
        self.order.save(update_fields=[
            "payment_status", "payment_channel", "transaction_id"
        ])
        provider_data = {
            "status": "REFUSED",
            "amount": "20.00",
            "currency": "EUR",
        }

        with patch(
            "payments.views._cinetpay_check_status",
            return_value=provider_data,
        ):
            response = self.client.post(
                reverse("payments:cinetpay_ipn"),
                data={"cpm_trans_id": payment.transaction_id},
            )

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(payment.status, "FAILED")
        self.assertEqual(self.order.payment_status, "FAILED")
        self.assertIsNone(self.order.cart_finalized_at)

    def test_get_initializers_have_no_side_effect(self):
        stripe_response = self.client.get(
            reverse("payments:stripe_checkout", args=[self.order.id])
        )
        cinetpay_response = self.client.get(
            reverse("payments:cinetpay_create", args=[self.order.id])
        )

        self.assertEqual(stripe_response.status_code, 405)
        self.assertEqual(cinetpay_response.status_code, 405)
        self.assertFalse(Payment.objects.exists())
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "PENDING")

    def test_payment_initializers_require_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        stripe_response = csrf_client.post(
            reverse("payments:stripe_checkout", args=[self.order.id])
        )
        cinetpay_response = csrf_client.post(
            reverse("payments:cinetpay_create", args=[self.order.id])
        )

        self.assertEqual(stripe_response.status_code, 403)
        self.assertEqual(cinetpay_response.status_code, 403)
        self.assertFalse(Payment.objects.exists())

    def test_new_stripe_attempt_after_failure_uses_fresh_identity(self):
        self.initiate_stripe()
        old_payment = Payment.objects.get()
        failed_event = {
            "type": "checkout.session.async_payment_failed",
            "data": {
                "object": {
                    "id": old_payment.transaction_id,
                    "metadata": {
                        "commande_id": str(self.order.id),
                        "payment_id": str(old_payment.id),
                    },
                }
            },
        }
        with patch(
            "payments.views.stripe.Webhook.construct_event",
            return_value=failed_event,
        ):
            response = self.client.post(
                reverse("payments:stripe_webhook"),
                data=b"{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="signature",
            )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "FAILED")
        choice = self.client.get(reverse("payments:choice", args=[self.order.id]))
        self.assertEqual(choice.status_code, 200)

        with patch(
            "payments.views.stripe.checkout.Session.create",
            return_value=self.stripe_session("cs_retry_order"),
        ):
            retry = self.client.post(
                reverse("payments:stripe_checkout", args=[self.order.id])
            )

        self.assertEqual(retry.status_code, 302)
        new_payment = Payment.objects.get(status="PROCESSING")
        old_payment.refresh_from_db()
        self.assertEqual(old_payment.status, "FAILED")
        self.assertNotEqual(new_payment.idempotency_key, old_payment.idempotency_key)
        self.assertNotEqual(new_payment.transaction_id, old_payment.transaction_id)

    def test_new_cinetpay_attempt_after_refusal_uses_fresh_identity(self):
        first_response = Mock()
        first_response.json.return_value = {
            "code": "201",
            "data": {"payment_url": "https://cinetpay.test/first"},
        }
        with patch("payments.views.requests.post", return_value=first_response):
            self.client.post(reverse("payments:cinetpay_create", args=[self.order.id]))
        old_payment = Payment.objects.get()
        refusal = {"status": "REFUSED", "amount": "20.00", "currency": "EUR"}
        with patch("payments.views._cinetpay_check_status", return_value=refusal):
            callback = self.client.post(
                reverse("payments:cinetpay_ipn"),
                data={"cpm_trans_id": old_payment.transaction_id},
            )
        self.assertEqual(callback.status_code, 200)

        retry_response = Mock()
        retry_response.json.return_value = {
            "code": "201",
            "data": {"payment_url": "https://cinetpay.test/retry"},
        }
        with patch("payments.views.requests.post", return_value=retry_response):
            retry = self.client.post(
                reverse("payments:cinetpay_create", args=[self.order.id])
            )

        self.assertEqual(retry.status_code, 302)
        new_payment = Payment.objects.get(status="PROCESSING")
        old_payment.refresh_from_db()
        self.assertEqual(old_payment.status, "FAILED")
        self.assertNotEqual(new_payment.idempotency_key, old_payment.idempotency_key)
        self.assertNotEqual(new_payment.transaction_id, old_payment.transaction_id)

    def test_expired_processing_attempt_is_canceled_and_replaced(self):
        self.initiate_stripe()
        old_payment = Payment.objects.get()
        Payment.objects.filter(pk=old_payment.pk).update(
            updated_at=timezone.now() - timedelta(hours=2)
        )

        with patch(
            "payments.views.stripe.checkout.Session.create",
            return_value=self.stripe_session("cs_after_expiration"),
        ):
            response = self.client.post(
                reverse("payments:stripe_checkout", args=[self.order.id])
            )

        self.assertEqual(response.status_code, 302)
        old_payment.refresh_from_db()
        new_payment = Payment.objects.get(status="PROCESSING")
        self.assertEqual(old_payment.status, "CANCELED")
        self.assertNotEqual(new_payment.pk, old_payment.pk)
        self.assertNotEqual(new_payment.idempotency_key, old_payment.idempotency_key)

    def test_old_callback_cannot_validate_replacement_attempt(self):
        self.initiate_stripe()
        old_payment = Payment.objects.get()
        Payment.objects.filter(pk=old_payment.pk).update(
            updated_at=timezone.now() - timedelta(hours=2)
        )
        with patch(
            "payments.views.stripe.checkout.Session.create",
            return_value=self.stripe_session("cs_current_attempt"),
        ):
            self.client.post(reverse("payments:stripe_checkout", args=[self.order.id]))
        old_payment.refresh_from_db()
        old_event = self.stripe_event(old_payment)

        with patch("payments.views.stripe.Webhook.construct_event", return_value=old_event):
            first = self.client.post(
                reverse("payments:stripe_webhook"),
                data=b"{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="signature",
            )
            second = self.client.post(
                reverse("payments:stripe_webhook"),
                data=b"{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="signature",
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.order.refresh_from_db()
        current_payment = Payment.objects.get(status="PROCESSING")
        self.assertEqual(self.order.payment_status, "PROCESSING")
        self.assertEqual(self.order.transaction_id, current_payment.transaction_id)
        self.assertIsNone(self.order.cart_finalized_at)
