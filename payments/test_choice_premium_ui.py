import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from payments.models import Adresse
from shop.models import Commande, LigneCommande, Produit


class PaymentChoicePremiumUITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="payment-choice-ui@example.test",
            password="test-password",
        )
        address = Adresse.objects.create(
            utilisateur=cls.user,
            rue="1 rue du Paiement",
            ville="Paris",
            code_postal="75001",
            pays="France",
        )
        product = Produit.objects.create(
            nom="Produit paiement premium",
            slug="produit-paiement-premium-ui",
            prix=Decimal("25.00"),
        )
        cls.order = Commande.objects.create(
            client=cls.user,
            adresse=address,
            total=Decimal("25.00"),
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
        self.client.force_login(self.user)
        self.url = reverse("payments:choice", args=[self.order.pk])

    @override_settings(STRIPE_ENABLED=True, CINETPAY_ENABLED=True)
    def test_choice_has_one_h1_fieldset_and_post_csrf_forms(self):
        response = self.client.get(self.url)
        markup = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(markup.count("<h1"), 1)
        self.assertContains(response, '<fieldset class="payment-methods">')
        self.assertContains(
            response,
            'action="{}" method="post"'.format(
                reverse("payments:stripe_checkout", args=[self.order.pk])
            ),
        )
        self.assertContains(
            response,
            'action="{}" method="post"'.format(
                reverse("payments:cinetpay_create", args=[self.order.pk])
            ),
        )
        self.assertGreaterEqual(markup.count('name="csrfmiddlewaretoken"'), 2)
        self.assertNotIn("STRIPE_SECRET", markup)
        self.assertNotIn(settings.CINETPAY_BASE_URL, markup)

    def test_payment_methods_follow_their_own_flags(self):
        stripe_url = reverse("payments:stripe_checkout", args=[self.order.pk])
        cinetpay_url = reverse("payments:cinetpay_create", args=[self.order.pk])
        cases = (
            (True, False, True, False),
            (False, True, False, True),
            (False, False, False, False),
        )

        for stripe_enabled, cinetpay_enabled, has_stripe, has_cinetpay in cases:
            with self.subTest(
                stripe=stripe_enabled,
                cinetpay=cinetpay_enabled,
            ), self.settings(
                STRIPE_ENABLED=stripe_enabled,
                CINETPAY_ENABLED=cinetpay_enabled,
                SUBSCRIPTIONS_ENABLED=not stripe_enabled,
            ):
                response = self.client.get(self.url)
                markup = response.content.decode()
                self.assertEqual(stripe_url in markup, has_stripe)
                self.assertEqual(cinetpay_url in markup, has_cinetpay)

        with self.settings(
            STRIPE_ENABLED=False,
            CINETPAY_ENABLED=False,
            SUBSCRIPTIONS_ENABLED=True,
        ):
            response = self.client.get(self.url)
            self.assertContains(response, "Paiement indisponible")
            self.assertContains(
                response,
                "Aucun moyen de paiement n’est disponible pour le moment.",
            )

    @override_settings(STRIPE_ENABLED=True, CINETPAY_ENABLED=True)
    def test_choice_displays_the_real_order_status(self):
        self.order.payment_status = "FAILED"
        self.order.save(update_fields=["payment_status"])

        response = self.client.get(self.url)

        self.assertContains(response, self.order.get_payment_status_display())
        self.assertNotContains(response, ">En attente de paiement<")

    def test_all_order_payment_starts_reject_get(self):
        for url in (
            reverse("payments:stripe_checkout", args=[self.order.pk]),
            reverse("payments:cinetpay_create", args=[self.order.pk]),
            reverse("payments:mobile_checkout", args=[self.order.pk]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 405)

    def test_anonymous_choice_redirects_to_login(self):
        self.client.logout()
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)


class PaymentChoicePremiumUIStaticTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = Path(settings.BASE_DIR)
        cls.styles = (base / "static/css/styles.css").read_text(encoding="utf-8")
        cls.payment_css = (
            base / "static/css/payment-choice.css"
        ).read_text(encoding="utf-8")
        cls.template = (
            base / "payments/templates/payments/choice.html"
        ).read_text(encoding="utf-8")

    def test_payment_css_uses_foundation_tokens_without_important(self):
        all_css = self.styles + "\n" + self.payment_css
        used = set(
            re.findall(r"var\(\s*(--[a-z0-9-]+)", self.payment_css, re.I)
        )
        defined = set(
            re.findall(r"(--[a-z0-9-]+)\s*:\s*[^;{}]+;", all_css, re.I)
        )

        self.assertEqual(used - defined, set())
        self.assertNotIn("!important", self.payment_css)
        self.assertIsNone(re.search(r"#[0-9a-f]{3,8}\b", self.payment_css, re.I))
        self.assertIsNone(re.search(r"\brgba?\(", self.payment_css, re.I))

    def test_payment_cards_are_static_and_responsive(self):
        self.assertNotIn(".payment-method-card:hover", self.payment_css)
        self.assertNotIn("transition:", self.payment_css.split(".payment-method-card", 1)[1].split("}", 1)[0])
        for marker in (
            "@media (max-width: 1099.98px)",
            "@media (max-width: 991.98px)",
            "@media (max-width: 767.98px)",
            "@media (max-width: 419.98px)",
            "@media (prefers-reduced-motion: reduce)",
        ):
            self.assertIn(marker, self.payment_css)
        self.assertNotRegex(self.template, r"\|safe\b")
