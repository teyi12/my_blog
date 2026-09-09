import json
import os
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from blog.settings import env_bool
from monetization.models import Don
from payments.donations import donations_are_available
from payments.models import Adresse, DonationPaymentAttempt, Payment
from shop.models import Commande, LigneCommande, Produit


class DonationAvailabilityTests(SimpleTestCase):
    def test_absent_environment_value_disables_donations(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(env_bool("DONATIONS_ENABLED", False))

    def test_only_explicit_true_environment_values_enable_donations(self):
        for value in ("true", "TRUE", "1", "yes", "Yes", "on", "ON"):
            with self.subTest(value=value), patch.dict(
                os.environ,
                {"DONATIONS_ENABLED": value},
                clear=True,
            ):
                self.assertTrue(env_bool("DONATIONS_ENABLED", False))

    def test_false_and_unknown_environment_values_disable_donations(self):
        for value in ("false", "0", "no", "off", "unexpected", "", "2"):
            with self.subTest(value=value), patch.dict(
                os.environ,
                {"DONATIONS_ENABLED": value},
                clear=True,
            ):
                self.assertFalse(env_bool("DONATIONS_ENABLED", False))

    def test_missing_stripe_secrets_disable_donations(self):
        cases = (
            ("", "whsec_configured"),
            ("sk_test_configured", ""),
            ("   ", "whsec_configured"),
            ("sk_test_configured", "   "),
        )
        for secret_key, webhook_secret in cases:
            with self.subTest(
                secret_key=bool(secret_key.strip()),
                webhook_secret=bool(webhook_secret.strip()),
            ), self.settings(
                DONATIONS_ENABLED=True,
                STRIPE_SECRET_KEY=secret_key,
                STRIPE_WEBHOOK_SECRET=webhook_secret,
                IS_PRODUCTION=False,
            ):
                self.assertFalse(donations_are_available())

    @override_settings(
        DONATIONS_ENABLED=True,
        STRIPE_SECRET_KEY="sk_test_configured",
        STRIPE_WEBHOOK_SECRET="whsec_configured",
        IS_PRODUCTION=True,
    )
    def test_test_key_never_enables_donations_in_production(self):
        self.assertFalse(donations_are_available())

    def test_live_secret_key_prefixes_enable_donations_in_production(self):
        for prefix in ("sk_live_", "rk_live_"):
            with self.subTest(prefix=prefix), self.settings(
                DONATIONS_ENABLED=True,
                STRIPE_SECRET_KEY=f"{prefix}configured",
                STRIPE_WEBHOOK_SECRET="whsec_configured",
                IS_PRODUCTION=True,
            ):
                self.assertTrue(donations_are_available())


@override_settings(
    DONATIONS_ENABLED=True,
    STRIPE_SECRET_KEY="sk_test_configured",
    STRIPE_WEBHOOK_SECRET="whsec_configured",
    IS_PRODUCTION=False,
)
class DonationCheckoutTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="donor@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.url = reverse("payments:create_donation_checkout")

    @staticmethod
    def stripe_session(session_id="cs_donation_test"):
        return SimpleNamespace(
            id=session_id,
            url="https://checkout.stripe.test/donation",
        )

    def test_get_is_rejected_without_calling_stripe(self):
        with patch("payments.views.stripe.checkout.Session.create") as create:
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        create.assert_not_called()
        self.assertFalse(DonationPaymentAttempt.objects.exists())

    @override_settings(DONATIONS_ENABLED=False)
    def test_disabled_direct_post_is_blocked_before_validation(self):
        with patch("payments.views.stripe.checkout.Session.create") as create:
            response = self.client.post(
                self.url,
                {"amount": "invalid"},
                follow=True,
            )

        self.assertRedirects(response, reverse("monetization:don"))
        self.assertContains(
            response,
            "Les dons sont temporairement indisponibles. Merci pour votre compréhension.",
        )
        create.assert_not_called()
        self.assertFalse(DonationPaymentAttempt.objects.exists())

    @override_settings(
        DONATIONS_ENABLED=True,
        STRIPE_SECRET_KEY="sk_test_configured",
        STRIPE_WEBHOOK_SECRET="whsec_configured",
        IS_PRODUCTION=True,
    )
    def test_production_test_key_blocks_direct_post(self):
        with patch("payments.views.stripe.checkout.Session.create") as create:
            response = self.client.post(self.url, {"amount": "5.00"})

        self.assertEqual(response.status_code, 302)
        create.assert_not_called()
        self.assertFalse(DonationPaymentAttempt.objects.exists())

    @override_settings(
        DONATIONS_ENABLED=True,
        STRIPE_SECRET_KEY="sk_live_configured",
        STRIPE_WEBHOOK_SECRET="whsec_configured",
        IS_PRODUCTION=True,
    )
    def test_production_live_configuration_allows_checkout(self):
        with patch(
            "payments.views.stripe.checkout.Session.create",
            return_value=self.stripe_session("cs_live_configuration"),
        ) as create:
            response = self.client.post(self.url, {"amount": "5.00"})

        self.assertEqual(response.status_code, 302)
        create.assert_called_once()
        self.assertEqual(DonationPaymentAttempt.objects.count(), 1)

    def test_eur_is_imposed_and_converted_with_minor_amount(self):
        with patch(
            "payments.views.stripe.checkout.Session.create",
            return_value=self.stripe_session(),
        ) as create:
            response = self.client.post(
                self.url,
                {"amount": "1.23", "currency": "xof"},
            )

        self.assertEqual(response.status_code, 302)
        attempt = DonationPaymentAttempt.objects.get()
        self.assertEqual(attempt.montant, Decimal("1.23"))
        self.assertEqual(attempt.devise, "EUR")
        price_data = create.call_args.kwargs["line_items"][0]["price_data"]
        self.assertEqual(price_data["currency"], "eur")
        self.assertEqual(price_data["unit_amount"], 123)

    def test_invalid_donation_amounts_are_rejected(self):
        invalid_amounts = (None, "", "invalid", "0", "-1", "NaN", "Infinity", "1.001")

        for amount in invalid_amounts:
            with self.subTest(amount=amount), patch(
                "payments.views.stripe.checkout.Session.create"
            ) as create:
                data = {} if amount is None else {"amount": amount}
                response = self.client.post(self.url, data)

                self.assertEqual(response.status_code, 302)
                create.assert_not_called()

        self.assertFalse(DonationPaymentAttempt.objects.exists())

    def test_attempt_exists_before_stripe_and_identifiers_are_transmitted(self):
        observed_attempt_ids = []

        def create_session(**kwargs):
            attempt = DonationPaymentAttempt.objects.get()
            self.assertEqual(attempt.status, "PROCESSING")
            self.assertIsNone(attempt.stripe_session_id)
            observed_attempt_ids.append(attempt.id)
            return self.stripe_session()

        with patch(
            "payments.views.stripe.checkout.Session.create",
            side_effect=create_session,
        ) as create:
            response = self.client.post(self.url, {"amount": "5.00"})

        self.assertEqual(response.status_code, 302)
        attempt = DonationPaymentAttempt.objects.get()
        self.assertEqual(observed_attempt_ids, [attempt.id])
        self.assertEqual(attempt.stripe_session_id, "cs_donation_test")
        self.assertEqual(
            create.call_args.kwargs["idempotency_key"],
            str(attempt.idempotency_key),
        )
        self.assertEqual(
            create.call_args.kwargs["metadata"],
            {
                "payment_kind": "donation",
                "donation_attempt_id": str(attempt.id),
                "user_id": str(self.user.id),
            },
        )

    def test_provider_initialization_failure_marks_attempt_failed(self):
        with patch(
            "payments.views.stripe.checkout.Session.create",
            side_effect=RuntimeError("provider unavailable"),
        ):
            response = self.client.post(self.url, {"amount": "5.00"})

        self.assertEqual(response.status_code, 302)
        attempt = DonationPaymentAttempt.objects.get()
        self.assertEqual(attempt.status, "FAILED")
        self.assertIsNone(attempt.don)
        self.assertEqual(attempt.raw_response["stage"], "initialization")
        self.assertEqual(attempt.raw_response["error_type"], "RuntimeError")

    def test_active_donation_form_has_no_client_currency_field(self):
        response = self.client.get(reverse("monetization:don"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="currency"')
        self.assertContains(response, 'name="amount"')
        self.assertContains(response, "€")


class DonationWebhookTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="webhook-donor@example.com",
            password="test-password",
        )
        self.url = reverse("payments:stripe_webhook")

    def create_attempt(self, suffix):
        return DonationPaymentAttempt.objects.create(
            utilisateur=self.user,
            montant=Decimal("5.00"),
            devise="EUR",
            stripe_session_id=f"cs_donation_{suffix}",
            checkout_url=f"https://checkout.stripe.test/{suffix}",
        )

    def event(self, attempt, event_type="checkout.session.completed", **overrides):
        session = {
            "id": attempt.stripe_session_id,
            "payment_status": "paid",
            "amount_total": 500,
            "currency": "eur",
            "metadata": {
                "payment_kind": "donation",
                "donation_attempt_id": str(attempt.id),
                "user_id": str(attempt.utilisateur_id),
            },
        }
        session.update(overrides)
        return {"type": event_type, "data": {"object": session}}

    def post_event(self, event):
        with patch(
            "payments.views.stripe.Webhook.construct_event",
            return_value=event,
        ):
            return self.client.post(
                self.url,
                data=json.dumps({}),
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="signature",
            )

    @override_settings(DONATIONS_ENABLED=False)
    def test_disabled_new_donations_do_not_block_existing_attempt_webhook(self):
        attempt = self.create_attempt("success")
        event = self.event(attempt)

        first = self.post_event(event)
        second = self.post_event(event)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, "SUCCESS")
        self.assertIsNotNone(attempt.don_id)
        self.assertEqual(Don.objects.count(), 1)
        self.assertEqual(attempt.don.utilisateur, self.user)
        self.assertEqual(attempt.don.montant, Decimal("5.00"))
        self.assertFalse(Payment.objects.exists())

    def test_completed_webhook_rejects_inconsistent_payment_data(self):
        other_user = get_user_model().objects.create_user(
            email="other-donor@example.com",
            password="test-password",
        )
        mismatches = {
            "amount": {"amount_total": 499},
            "currency": {"currency": "usd"},
            "session": {"id": "cs_wrong"},
            "user": {
                "metadata": {
                    "payment_kind": "donation",
                    "donation_attempt_id": None,
                    "user_id": str(other_user.id),
                }
            },
        }

        for index, (name, overrides) in enumerate(mismatches.items()):
            with self.subTest(mismatch=name):
                attempt = self.create_attempt(f"mismatch_{index}")
                if name == "user":
                    overrides["metadata"]["donation_attempt_id"] = str(attempt.id)
                response = self.post_event(self.event(attempt, **overrides))

                self.assertIn(response.status_code, (400, 404))
                attempt.refresh_from_db()
                self.assertEqual(attempt.status, "PROCESSING")
                self.assertIsNone(attempt.don_id)

        self.assertFalse(Don.objects.exists())

    def test_unpaid_completed_webhook_is_rejected(self):
        attempt = self.create_attempt("unpaid")

        response = self.post_event(
            self.event(attempt, payment_status="unpaid")
        )

        self.assertEqual(response.status_code, 400)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, "PROCESSING")
        self.assertIsNone(attempt.don_id)

    def test_failed_and_expired_webhooks_are_idempotent_without_donation(self):
        cases = (
            ("checkout.session.async_payment_failed", "FAILED"),
            ("checkout.session.expired", "CANCELED"),
        )

        for index, (event_type, expected_status) in enumerate(cases):
            with self.subTest(event_type=event_type):
                attempt = self.create_attempt(f"terminal_{index}")
                event = self.event(attempt, event_type=event_type)

                first = self.post_event(event)
                second = self.post_event(event)

                self.assertEqual(first.status_code, 200)
                self.assertEqual(second.status_code, 200)
                attempt.refresh_from_db()
                self.assertEqual(attempt.status, expected_status)
                self.assertIsNone(attempt.don_id)

        self.assertFalse(Don.objects.exists())

    def test_donation_webhook_locks_only_the_donation_attempt(self):
        attempt = self.create_attempt("lock")
        real_attempt_lock = DonationPaymentAttempt.objects.select_for_update
        real_payment_lock = Payment.objects.select_for_update

        with patch.object(
            DonationPaymentAttempt.objects,
            "select_for_update",
            wraps=real_attempt_lock,
        ) as attempt_lock, patch.object(
            Payment.objects,
            "select_for_update",
            wraps=real_payment_lock,
        ) as payment_lock:
            response = self.post_event(self.event(attempt))

        self.assertEqual(response.status_code, 200)
        attempt_lock.assert_called_once_with()
        payment_lock.assert_not_called()


@override_settings(
    DONATIONS_ENABLED=False,
    STRIPE_SECRET_KEY="sk_test_configured",
    STRIPE_WEBHOOK_SECRET="whsec_configured",
    IS_PRODUCTION=False,
)
class DonationUnavailableTemplateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="unavailable-donor@example.com",
            password="test-password",
        )
        address = Adresse.objects.create(
            utilisateur=cls.user,
            rue="1 Test Street",
            ville="Berlin",
            code_postal="10115",
            pays="Deutschland",
        )
        product = Produit.objects.create(
            nom="Produit test",
            slug="produit-donation-indisponible",
            prix=Decimal("5.00"),
        )
        cls.order = Commande.objects.create(
            client=cls.user,
            adresse=address,
            total=Decimal("5.00"),
            currency="EUR",
            payment_status="PENDING",
        )
        LigneCommande.objects.create(
            commande=cls.order,
            produit=product,
            quantite=1,
            prix_unitaire=product.prix,
        )

    def setUp(self):
        self.addCleanup(translation.activate, "fr")
        self.client.force_login(self.user)

    def test_public_page_is_accessible_without_active_form_in_each_language(self):
        cases = {
            "fr": (
                "/monetization/don/",
                "Les dons sont temporairement indisponibles. Merci pour votre compréhension.",
            ),
            "de": (
                "/de/monetization/don/",
                "Spenden sind vorübergehend nicht verfügbar. Vielen Dank für Ihr Verständnis.",
            ),
            "en": (
                "/en/monetization/don/",
                "Donations are temporarily unavailable. Thank you for your understanding.",
            ),
        }
        for language, (url, message) in cases.items():
            with self.subTest(language=language):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, message)
                self.assertNotContains(response, 'action="/payments/donate/"')

    def test_payment_choice_has_no_active_donation_form(self):
        response = self.client.get(
            reverse("payments:choice", args=[self.order.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Les dons sont temporairement indisponibles. Merci pour votre compréhension.",
        )
        self.assertNotContains(response, 'action="/payments/donate/"')

    def test_legacy_donation_template_has_no_active_form(self):
        with translation.override("fr"):
            html = render_to_string(
                "payments/donate.html",
                {"donations_available": False},
            )

        self.assertIn(
            "Les dons sont temporairement indisponibles. Merci pour votre compréhension.",
            html,
        )
        self.assertNotIn('action="/payments/donate/"', html)
