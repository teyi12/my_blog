import re
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from payments.models import Adresse, Payment
from payments.views import STRIPE_ORDER_CANCEL_TOKEN_SALT
from shop.models import Commande, LigneCommande, OrderCancellation, Produit


class PaymentResultPremiumUITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(
            email="payment-result-owner@example.test",
            password="test-password",
        )
        cls.other_user = user_model.objects.create_user(
            email="payment-result-other@example.test",
            password="test-password",
        )

    def setUp(self):
        self.client.force_login(self.owner)
        self.address = Adresse.objects.create(
            utilisateur=self.owner,
            rue="8 rue des Résultats",
            ville="Paris",
            code_postal="75001",
            pays="France",
        )
        self.product = Produit.objects.create(
            nom="Carnet de paiement",
            slug="carnet-payment-result-ui",
            prix=Decimal("24.00"),
        )
        self.order = Commande.objects.create(
            client=self.owner,
            adresse=self.address,
            total=Decimal("24.00"),
            currency="EUR",
            payment_status="PROCESSING",
            payment_channel="STRIPE",
        )
        LigneCommande.objects.create(
            commande=self.order,
            produit=self.product,
            quantite=1,
            prix_unitaire=self.product.prix,
        )
        self.payment = Payment.objects.create(
            commande=self.order,
            montant=self.order.total,
            devise=self.order.currency,
            transaction_id="provider-secret-result-id",
            channel="STRIPE",
            status="PROCESSING",
            raw_response={"secret": "provider-private-payload"},
        )

    def cancel_url(self, *, token=None, user_id=None, payment=None):
        payment = payment or self.payment
        if token is None:
            token = signing.dumps(
                {
                    "order_id": self.order.pk,
                    "payment_id": payment.pk,
                    "user_id": self.owner.pk if user_id is None else user_id,
                },
                salt=STRIPE_ORDER_CANCEL_TOKEN_SALT,
                compress=True,
            )
        return "{}?{}".format(
            reverse("payments:cancel"),
            urlencode({"order_context": token}),
        )

    def assert_single_accessible_result(self, response, *, role):
        markup = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(markup.count("<h1"), 1)
        self.assertIn('aria-labelledby="payment-result-title"', markup)
        self.assertIn('aria-hidden="true"', markup)
        self.assertIn(f'role="{role}"', markup)
        self.assertNotIn("provider-private-payload", markup)
        self.assertNotIn("provider-secret-result-id", markup)

    def test_generic_success_is_pending_and_does_not_mutate_or_call_a_provider(self):
        order_state = (self.order.payment_status, self.order.fulfillment_status)
        payment_state = self.payment.status

        with patch("payments.views._cinetpay_check_status") as provider_call:
            response = self.client.get(reverse("payments:success"))

        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        self.assert_single_accessible_result(response, role="status")
        self.assertContains(response, "Votre paiement est en cours de vérification.")
        self.assertContains(response, reverse("shop:mes_commandes"))
        self.assertNotContains(response, "Votre paiement est confirmé")
        self.assertEqual(
            (self.order.payment_status, self.order.fulfillment_status),
            order_state,
        )
        self.assertEqual(self.payment.status, payment_state)
        provider_call.assert_not_called()

    def test_donation_and_subscription_pending_contexts_keep_useful_routes(self):
        cases = (
            (
                "donation",
                "Votre don est en cours de vérification.",
                reverse("monetization:don"),
            ),
            (
                "subscription",
                "Votre souscription est en cours de vérification.",
                reverse("monetization:abonnements"),
            ),
        )
        for kind, title, secondary_url in cases:
            with self.subTest(kind=kind):
                response = self.client.get(
                    reverse("payments:success"),
                    {"payment_kind": kind},
                )
                self.assertContains(response, title)
                self.assertContains(response, secondary_url)
                self.assertEqual(response.content.decode().count("<h1"), 1)

    def test_valid_signed_context_shows_only_an_authorized_payable_summary(self):
        response = self.client.get(self.cancel_url())

        self.assert_single_accessible_result(response, role="status")
        self.assertContains(response, f"#{self.order.pk}")
        self.assertContains(
            response,
            reverse("payments:choice", args=[self.order.pk]),
        )
        self.assertContains(response, "Reprendre le paiement de cette commande")
        self.assertNotContains(response, self.address.rue)

    def test_invalid_foreign_and_wrong_channel_contexts_reveal_no_order(self):
        wrong_channel_payment = Payment.objects.create(
            commande=self.order,
            montant=self.order.total,
            devise=self.order.currency,
            transaction_id="cinetpay-private-result-id",
            channel="CINETPAY",
            status="CANCELED",
        )
        cases = (
            self.cancel_url(token="invalid-signed-value"),
            self.cancel_url(user_id=self.other_user.pk),
            self.cancel_url(payment=wrong_channel_payment),
        )
        for url in cases:
            with self.subTest(url=url):
                response = self.client.get(url)
                markup = response.content.decode()
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('class="payment-result-summary"', markup)
                self.assertNotIn(self.address.rue, markup)
                self.assertNotIn(
                    reverse("shop:ma_commande_detail", args=[self.order.pk]),
                    markup,
                )

        self.client.force_login(self.other_user)
        response = self.client.get(self.cancel_url())
        self.assertNotContains(response, 'class="payment-result-summary"')
        self.assertNotContains(response, self.owner.email)
        self.assertNotContains(response, self.address.rue)

    def test_explicitly_canceled_and_paid_orders_never_offer_payment_resume(self):
        cases = (
            ("SUCCESS", "Cette commande est déjà payée."),
            ("REFUNDED", "Le paiement de cette commande a été remboursé."),
        )
        for status, title in cases:
            with self.subTest(status=status):
                self.order.payment_status = status
                self.order.save(update_fields=["payment_status"])
                response = self.client.get(self.cancel_url())
                self.assertContains(response, title)
                self.assertNotContains(
                    response,
                    reverse("payments:choice", args=[self.order.pk]),
                )
                self.assertContains(
                    response,
                    reverse("shop:ma_commande_detail", args=[self.order.pk]),
                )

        OrderCancellation.objects.create(
            commande=self.order,
            requested_by=self.owner,
            source="CUSTOMER",
        )
        self.order.payment_status = "CANCELED"
        self.order.fulfillment_status = "CANCELED"
        self.order.save(update_fields=["payment_status", "fulfillment_status"])
        response = self.client.get(self.cancel_url())
        self.assertContains(response, "Cette commande a déjà été annulée")
        self.assertNotContains(
            response,
            reverse("payments:choice", args=[self.order.pk]),
        )

    def test_generic_cancel_keeps_a_generic_path_without_order_details(self):
        response = self.client.get(reverse("payments:cancel"))

        self.assert_single_accessible_result(response, role="status")
        self.assertContains(response, "Aucun paiement n’a été finalisé.")
        self.assertContains(response, reverse("payments:choice"))
        self.assertNotContains(response, 'class="payment-result-summary"')

    def test_cinetpay_result_states_use_safe_distinct_templates(self):
        cases = (
            ("ACCEPTED", "Votre paiement est en cours de vérification.", "status"),
            ("PENDING", "Votre paiement est en cours de vérification.", "status"),
            ("CANCELED", "Aucun paiement n’a été finalisé.", "status"),
            ("REFUSED", "Le paiement n’a pas pu être confirmé.", "alert"),
        )
        for provider_status, expected, role in cases:
            with self.subTest(status=provider_status), patch(
                "payments.views._cinetpay_check_status",
                return_value={
                    "status": provider_status,
                    "error": "private-provider-exception",
                },
            ):
                response = self.client.get(
                    reverse("payments:cinetpay_return"),
                    {"transaction_id": "external-private-id"},
                )
                self.assert_single_accessible_result(response, role=role)
                self.assertContains(response, expected)
                self.assertNotContains(response, "private-provider-exception")
                self.assertNotContains(response, "external-private-id")


class PaymentResultPremiumUIStaticTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = Path(settings.BASE_DIR)
        cls.foundation_css = (base / "static/css/styles.css").read_text(
            encoding="utf-8"
        )
        cls.page_css = (base / "static/css/payment-result.css").read_text(
            encoding="utf-8"
        )
        cls.templates = "\n".join(
            (base / path).read_text(encoding="utf-8")
            for path in (
                "payments/templates/payments/success.html",
                "payments/templates/payments/cancel.html",
                "payments/templates/payments/error.html",
            )
        )

    def test_result_css_uses_defined_tokens_without_raw_colors_or_important(self):
        all_css = self.foundation_css + "\n" + self.page_css
        used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", self.page_css, re.I))
        defined = set(
            re.findall(r"(--[a-z0-9-]+)\s*:\s*[^;{}]+;", all_css, re.I)
        )
        self.assertEqual(used - defined, set())
        self.assertNotIn("!important", self.page_css)
        self.assertIsNone(re.search(r"#[0-9a-f]{3,8}\b", self.page_css, re.I))
        self.assertIsNone(re.search(r"\brgba?\(", self.page_css, re.I))

    def test_result_pages_are_static_safe_and_structurally_responsive(self):
        self.assertNotIn("animation:", self.page_css)
        self.assertNotIn("transition:", self.page_css)
        for marker in (
            "@media (max-width: 1023.98px)",
            "@media (max-width: 767.98px)",
            "@media (max-width: 419.98px)",
            "@media (prefers-reduced-motion: reduce)",
        ):
            self.assertIn(marker, self.page_css)
        self.assertNotRegex(self.templates, r"\|safe\b")
        self.assertNotIn("<script", self.templates)
