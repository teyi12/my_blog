from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import translation

from payments.models import Adresse
from shop.models import Commande, LigneCommande, Produit
from shop.shipping import send_fulfillment_notification


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="shop@example.com",
    SITE_BASE_URL="https://example.test",
)
class FulfillmentNotificationI18nTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="notifications@example.com",
            first_name="Ada",
        )
        cls.address = Adresse.objects.create(
            utilisateur=cls.user,
            rue="1 Test Street",
            ville="Berlin",
            code_postal="10115",
            pays="Deutschland",
        )
        cls.product = Produit.objects.create(
            nom_fr="Produit notifié",
            nom_de="Benachrichtigtes Produkt",
            nom_en="Notified product",
            slug="notified-product",
            prix=Decimal("20.00"),
        )

    def _order(self, language):
        order = Commande.objects.create(
            client=self.user,
            adresse=self.address,
            total=Decimal("20.00"),
            payment_status="SUCCESS",
            fulfillment_status="SHIPPED",
            carrier="DHL",
            tracking_number=f"TRACK-{language}",
            language_code=language,
        )
        with translation.override(language):
            LigneCommande.objects.create(
                commande=order,
                produit=self.product,
                quantite=1,
                prix_unitaire=self.product.prix,
            )
        return order

    def setUp(self):
        self.addCleanup(translation.activate, "fr")

    def test_shipping_email_uses_the_language_stored_on_the_order(self):
        cases = {
            "fr": ("a été expédiée", "Produit notifié", "/shop/mes-commandes/"),
            "de": ("wurde versandt", "Benachrichtigtes Produkt", "/de/shop/mes-commandes/"),
            "en": ("has shipped", "Notified product", "/en/shop/mes-commandes/"),
        }
        for language, (subject_text, product_name, path) in cases.items():
            with self.subTest(language=language):
                mail.outbox.clear()
                order = self._order(language)
                self.assertTrue(send_fulfillment_notification(order, "SHIPPED"))
                self.assertEqual(len(mail.outbox), 1)
                message = mail.outbox[0]
                self.assertIn(subject_text, message.subject)
                self.assertIn(path, message.body)
                self.assertIn(product_name, message.alternatives[0].content)
                self.assertIn(f'lang="{language}"', message.alternatives[0].content)

    def test_delivery_email_uses_the_language_stored_on_the_order(self):
        for language, expected in {
            "fr": "a été livrée",
            "de": "wurde geliefert",
            "en": "has been delivered",
        }.items():
            with self.subTest(language=language):
                mail.outbox.clear()
                order = self._order(language)
                self.assertTrue(send_fulfillment_notification(order, "DELIVERED"))
                self.assertIn(expected, mail.outbox[0].subject)
