from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from payments.models import Adresse, Payment
from shop.models import Commande, LigneCommande, Produit


class PaymentPagesI18nTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="payment-i18n@example.com", password="test-password"
        )
        cls.address = Adresse.objects.create(
            utilisateur=cls.user,
            rue="1 Payment Street",
            ville="Berlin",
            code_postal="10115",
            pays="Deutschland",
        )
        cls.product = Produit.objects.create(
            nom_fr="Produit paiement",
            nom_de="Zahlungsprodukt",
            nom_en="Payment product",
            slug="payment-product-stable",
            prix=Decimal("20.00"),
        )
        cls.order = Commande.objects.create(
            client=cls.user,
            adresse=cls.address,
            total=Decimal("20.00"),
            currency="EUR",
            payment_status="PENDING",
        )
        LigneCommande.objects.create(
            commande=cls.order,
            produit=cls.product,
            quantite=1,
            prix_unitaire=cls.product.prix,
        )

    def setUp(self):
        self.addCleanup(translation.activate, "fr")
        self.client.force_login(self.user)

    def _select_language(self, language, next_url):
        response = self.client.post(
            reverse("set_language"),
            {"language": language, "next": next_url},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, next_url)
        self.assertEqual(response.cookies[settings.LANGUAGE_COOKIE_NAME].value, language)

    def test_unprefixed_payment_pages_use_the_language_cookie(self):
        choice_url = reverse("payments:choice", args=[self.order.pk])
        self.assertEqual(choice_url, f"/payments/choice/{self.order.pk}/")
        cases = {
            "fr": ("Choisissez votre moyen de paiement", "Paiement réussi", "Aucun paiement n’a été finalisé."),
            "de": ("Wählen Sie Ihre Zahlungsmethode", "Zahlung erfolgreich", "Es wurde keine Zahlung abgeschlossen."),
            "en": ("Choose your payment method", "Payment successful", "No payment was completed."),
        }
        for language, expected in cases.items():
            with self.subTest(language=language):
                self._select_language(language, choice_url)
                choice = self.client.get(choice_url)
                success = self.client.get(reverse("payments:success"))
                cancel = self.client.get(reverse("payments:cancel"))
                self.assertEqual(choice.wsgi_request.LANGUAGE_CODE, language)
                self.assertContains(choice, expected[0])
                self.assertContains(success, expected[1])
                self.assertContains(cancel, expected[2])
                self.assertContains(choice, f'action="/payments/checkout/card/{self.order.pk}/"')
                self.assertContains(choice, f'action="/payments/cinetpay/{self.order.pk}/"')

    def test_payment_paths_remain_unprefixed_in_every_language(self):
        for language in ("fr", "de", "en"):
            with self.subTest(language=language), translation.override(language):
                self.assertEqual(reverse("payments:choice", args=[self.order.pk]), f"/payments/choice/{self.order.pk}/")
                self.assertEqual(reverse("payments:stripe_checkout", args=[self.order.pk]), f"/payments/checkout/card/{self.order.pk}/")
                self.assertEqual(reverse("payments:cinetpay_create", args=[self.order.pk]), f"/payments/cinetpay/{self.order.pk}/")
                self.assertEqual(reverse("payments:stripe_webhook"), "/payments/webhook/")
                self.assertEqual(reverse("payments:cinetpay_ipn"), "/payments/cinetpay/ipn/")

    def test_payment_choice_labels_follow_the_active_language(self):
        for language, expected in {
            "fr": ("Réussi", "Carte bancaire"),
            "de": ("Erfolgreich", "Kreditkarte"),
            "en": ("Successful", "Credit card"),
        }.items():
            with self.subTest(language=language), translation.override(language):
                payment = Payment(
                    commande=self.order,
                    montant=self.order.total,
                    devise="EUR",
                    transaction_id=f"choice-{language}",
                    status="SUCCESS",
                    channel="CARD",
                )
                self.assertEqual(payment.get_status_display(), expected[0])
                self.assertEqual(payment.get_channel_display(), expected[1])

    def test_python_payment_conflict_message_uses_the_cookie_language(self):
        Payment.objects.create(
            commande=self.order,
            montant=self.order.total,
            devise=self.order.currency,
            transaction_id="active-stripe-payment",
            channel="STRIPE",
            status="PROCESSING",
        )
        self.order.payment_status = "PROCESSING"
        self.order.payment_channel = "STRIPE"
        self.order.transaction_id = "active-stripe-payment"
        self.order.save(update_fields=["payment_status", "payment_channel", "transaction_id"])

        cases = {
            "fr": "Une autre tentative de paiement est déjà active.",
            "de": "Ein anderer Zahlungsversuch ist bereits aktiv.",
            "en": "Another payment attempt is already active.",
        }
        for language, expected in cases.items():
            with self.subTest(language=language):
                self._select_language(language, reverse("payments:choice", args=[self.order.pk]))
                with patch("payments.views.requests.post") as provider_call:
                    response = self.client.post(reverse("payments:cinetpay_create", args=[self.order.pk]))
                self.assertEqual(response.status_code, 409)
                self.assertContains(response, expected, status_code=409)
                provider_call.assert_not_called()
