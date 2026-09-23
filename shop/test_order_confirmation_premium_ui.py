import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import translation

from payments.models import Adresse
from shop.models import Commande, LigneCommande, OrderCancellation, Produit


class OrderConfirmationPremiumUITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(
            email="confirmation-owner@example.test",
            password="test-password",
        )
        cls.other_user = user_model.objects.create_user(
            email="confirmation-other@example.test",
            password="test-password",
        )

    def setUp(self):
        self.client.force_login(self.owner)
        self.address = Adresse.objects.create(
            utilisateur=self.owner,
            rue="<script>alert('address')</script>",
            ville="Berlin-mit-einem-sehr-langen-Ortsnamen",
            code_postal="10115",
            pays="Deutschland",
        )
        self.product = Produit.objects.create(
            nom_fr="<script>alert('product')</script>",
            nom_de="Historisches deutsches Produkt",
            nom_en="Historical English product",
            slug="order-confirmation-premium-ui",
            prix=Decimal("29.90"),
        )
        with translation.override("fr"):
            self.order = Commande.objects.create(
                client=self.owner,
                adresse=self.address,
                total=Decimal("59.80"),
                currency="EUR",
                language_code="fr",
                payment_status="PENDING",
                fulfillment_status="WAITING_PAYMENT",
            )
            self.line = LigneCommande.objects.create(
                commande=self.order,
                produit=self.product,
                quantite=2,
                prix_unitaire=self.product.prix,
            )
        self.url = reverse("shop:confirmation", args=[self.order.pk])

    def set_order_state(self, payment_status, fulfillment_status="WAITING_PAYMENT"):
        self.order.payment_status = payment_status
        self.order.fulfillment_status = fulfillment_status
        self.order.save(update_fields=["payment_status", "fulfillment_status"])

    def test_confirmation_renders_each_business_state_with_the_correct_cta(self):
        choice_url = reverse("payments:choice", args=[self.order.pk])
        states = (
            (
                "PENDING",
                "Votre commande est prête pour le paiement.",
                True,
            ),
            (
                "PROCESSING",
                "Votre paiement est en cours de vérification.",
                False,
            ),
            (
                "FAILED",
                "Le paiement de cette commande n’a pas abouti.",
                True,
            ),
            (
                "CANCELED",
                "La tentative de paiement a été interrompue.",
                True,
            ),
            (
                "SUCCESS",
                "Votre commande est confirmée.",
                False,
            ),
            (
                "REFUNDED",
                "Le paiement de cette commande a été remboursé.",
                False,
            ),
        )
        for status, title, should_offer_payment in states:
            with self.subTest(status=status):
                self.set_order_state(status)
                response = self.client.get(self.url)
                markup = response.content.decode()
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, title)
                self.assertEqual(markup.count("<h1"), 1)
                self.assertEqual(choice_url in markup, should_offer_payment)
                self.assertContains(response, self.order.get_payment_status_display())
                self.assertContains(
                    response,
                    self.order.get_fulfillment_status_display(),
                )

    def test_explicit_order_cancellation_is_not_presented_as_retryable(self):
        OrderCancellation.objects.create(
            commande=self.order,
            requested_by=self.owner,
            source="CUSTOMER",
        )
        self.set_order_state("CANCELED", "CANCELED")

        response = self.client.get(self.url)

        self.assertContains(response, "Cette commande a été annulée.")
        self.assertNotContains(
            response,
            reverse("payments:choice", args=[self.order.pk]),
        )
        self.assertContains(
            response,
            reverse("shop:ma_commande_detail", args=[self.order.pk]),
        )

    def test_payment_and_fulfillment_are_separate_accessible_states(self):
        self.set_order_state("SUCCESS", "SHIPPED")

        response = self.client.get(self.url)
        markup = response.content.decode()

        self.assertContains(response, 'data-payment-state="success"')
        self.assertContains(response, 'data-fulfillment-state="shipped"')
        self.assertContains(response, "Statut du paiement")
        self.assertContains(response, "État logistique")
        self.assertContains(response, 'aria-labelledby="order-status-title"')
        self.assertContains(response, 'role="status"')
        self.assertEqual(markup.count("<h1"), 1)
        self.assertIn('aria-hidden="true"', markup)

    def test_confirmation_escapes_snapshots_and_confines_private_data_to_owner(self):
        response = self.client.get(self.url)

        self.assertContains(
            response,
            "&lt;script&gt;alert(&#x27;product&#x27;)&lt;/script&gt;",
        )
        self.assertContains(
            response,
            "&lt;script&gt;alert(&#x27;address&#x27;)&lt;/script&gt;",
        )
        self.assertNotContains(response, "<script>alert('product')</script>")

        self.client.force_login(self.other_user)
        denied = self.client.get(self.url)
        self.assertEqual(denied.status_code, 404)
        self.assertNotContains(
            denied,
            "Historisches deutsches Produkt",
            status_code=404,
        )
        self.assertNotContains(
            denied,
            "Berlin-mit-einem-sehr-langen-Ortsnamen",
            status_code=404,
        )

    def test_ui_translation_follows_active_language_but_snapshot_stays_historical(self):
        self.set_order_state("SUCCESS", "TO_PREPARE")
        expected = {
            "fr": "Votre commande est confirmée.",
            "de": "Ihre Bestellung ist bestätigt.",
            "en": "Your order is confirmed.",
        }
        for language, title in expected.items():
            with self.subTest(language=language), translation.override(language):
                prefix = "" if language == "fr" else f"/{language}"
                response = self.client.get(
                    f"{prefix}/shop/confirmation/{self.order.pk}/"
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, title)
                self.assertContains(
                    response,
                    "&lt;script&gt;alert(&#x27;product&#x27;)&lt;/script&gt;",
                )
                self.assertNotContains(response, "Historisches deutsches Produkt")
                self.assertNotContains(response, "Historical English product")


class OrderConfirmationPremiumUIStaticTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = Path(settings.BASE_DIR)
        cls.foundation_css = (base / "static/css/styles.css").read_text(
            encoding="utf-8"
        )
        cls.page_css = (base / "static/css/order-confirmation.css").read_text(
            encoding="utf-8"
        )
        cls.template = (
            base / "shop/templates/shop/confirmation.html"
        ).read_text(encoding="utf-8")

    def test_confirmation_css_uses_only_defined_tokens_and_no_raw_colors(self):
        all_css = self.foundation_css + "\n" + self.page_css
        used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", self.page_css, re.I))
        defined = set(
            re.findall(r"(--[a-z0-9-]+)\s*:\s*[^;{}]+;", all_css, re.I)
        )
        self.assertEqual(used - defined, set())
        self.assertNotIn("!important", self.page_css)
        self.assertIsNone(re.search(r"#[0-9a-f]{3,8}\b", self.page_css, re.I))
        self.assertIsNone(re.search(r"\brgba?\(", self.page_css, re.I))

    def test_confirmation_is_static_safe_and_structurally_responsive(self):
        self.assertNotIn("animation:", self.page_css)
        self.assertNotIn("transition:", self.page_css)
        for marker in (
            "@media (max-width: 1023.98px)",
            "@media (max-width: 767.98px)",
            "@media (max-width: 419.98px)",
            "@media (prefers-reduced-motion: reduce)",
        ):
            self.assertIn(marker, self.page_css)
        self.assertNotRegex(self.template, r"\|safe\b")
        self.assertNotIn("<script", self.template)
