from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from payments.models import Adresse, Payment
from shop.forms import CommandeExpeditionForm, CommandeTraitementForm
from shop.models import Cart, CartItem, Categorie, Commande, LigneCommande, Produit


class CheckoutI18nPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="checkout-i18n@example.com",
            password="test-password",
            first_name="Ada",
        )
        cls.category = Categorie.objects.create(
            nom_fr="Livres français",
            nom_de="Deutsche Bücher",
            nom_en="English books",
            slug="livres-stables",
        )
        cls.product = Produit.objects.create(
            nom_fr="Produit français",
            nom_de="Deutsches Produkt",
            nom_en="English product",
            description_fr="Description française",
            slug="produit-stable",
            prix=Decimal("12.50"),
            categorie=cls.category,
        )
        cls.fallback_product = Produit.objects.create(
            nom_fr="Produit sans traduction",
            description_fr="Description de repli",
            slug="produit-repli-stable",
            prix=Decimal("7.00"),
            categorie=cls.category,
        )

    def setUp(self):
        self.addCleanup(translation.activate, "fr")
        self.client.force_login(self.user)
        self.cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(
            cart=self.cart,
            produit=self.product,
            quantite=2,
            prix_unitaire=self.product.prix,
        )
        CartItem.objects.create(
            cart=self.cart,
            produit=self.fallback_product,
            quantite=1,
            prix_unitaire=self.fallback_product.prix,
        )

    def _checkout_path(self, language):
        return "/shop/checkout/" if language == "fr" else f"/{language}/shop/checkout/"

    def _cart_path(self, language):
        return "/shop/panier/" if language == "fr" else f"/{language}/shop/panier/"

    def _order(self, language="fr"):
        address = Adresse.objects.create(
            utilisateur=self.user,
            rue="1 rue du Test",
            ville="Paris",
            code_postal="75001",
            pays="France",
        )
        order = Commande.objects.create(
            client=self.user,
            adresse=address,
            source_cart=self.cart,
            total=Decimal("32.00"),
            payment_status="SUCCESS",
            payment_channel="STRIPE",
            fulfillment_status="SHIPPED",
            carrier="DHL",
            tracking_number="TRACK-I18N",
            language_code=language,
        )
        LigneCommande.objects.create(
            commande=order,
            produit=self.product,
            quantite=2,
            prix_unitaire=self.product.prix,
        )
        return order

    def test_cart_static_dynamic_and_javascript_texts_are_translated(self):
        cases = {
            "fr": ("Votre panier", "Produit français", "Livres français", "Quantité mise à jour."),
            "de": ("Ihr Warenkorb", "Deutsches Produkt", "Deutsche Bücher", "Menge aktualisiert."),
            "en": ("Your cart", "English product", "English books", "Quantity updated."),
        }
        for language, expected in cases.items():
            with self.subTest(language=language):
                response = self.client.get(self._cart_path(language))
                self.assertEqual(response.status_code, 200)
                for text in expected:
                    self.assertContains(response, text)
                self.assertContains(response, "Produit sans traduction")
                self.assertContains(response, f'href="/{language}/shop/produit/produit-stable/"' if language != "fr" else 'href="/shop/produit/produit-stable/"')

    def test_checkout_page_and_address_validation_are_translated(self):
        cases = {
            "fr": ("Finaliser votre commande", "Rue", "Ce champ est obligatoire."),
            "de": ("Ihre Bestellung abschließen", "Straße und Hausnummer", "Dieses Feld ist erforderlich."),
            "en": ("Complete your order", "Street address", "This field is required."),
        }
        for language, (heading, label, error) in cases.items():
            with self.subTest(language=language):
                path = self._checkout_path(language)
                get_response = self.client.get(path)
                self.assertContains(get_response, heading)
                self.assertContains(get_response, label)
                self.assertContains(get_response, "Produit sans traduction")
                token = get_response.context["checkout_token"]
                post_response = self.client.post(path, {"checkout_token": str(token)})
                self.assertEqual(post_response.status_code, 200)
                self.assertContains(post_response, error, count=4)

    def test_checkout_records_the_active_language_on_the_order(self):
        for language in ("fr", "de", "en"):
            with self.subTest(language=language):
                path = self._checkout_path(language)
                token = self.client.get(path).context["checkout_token"]
                response = self.client.post(
                    path,
                    {
                        "checkout_token": str(token),
                        "rue": "1 rue du Test",
                        "ville": "Paris",
                        "code_postal": "75001",
                        "pays": "France",
                        "telephone": "0102030405",
                    },
                )
                order = Commande.objects.get(checkout_token=token)
                self.assertEqual(order.language_code, language)
                self.assertEqual(
                    order.lignes.get(produit=self.product).nom_produit_snapshot,
                    {
                        "fr": "Produit français",
                        "de": "Deutsches Produkt",
                        "en": "English product",
                    }[language],
                )
                expected_prefix = "" if language == "fr" else f"/{language}"
                self.assertRedirects(
                    response,
                    f"{expected_prefix}/shop/adresse-enregistree/?order_id={order.pk}",
                    fetch_redirect_response=False,
                )

    def test_address_saved_confirmation_and_customer_order_pages_are_translated(self):
        order = self._order()
        cases = {
            "fr": ("Adresse enregistrée avec succès", "Votre commande est prête", "Suivi de votre commande"),
            "de": ("Adresse erfolgreich gespeichert", "Ihre Bestellung ist zur Zahlung bereit", "Ihre Bestellung verfolgen"),
            "en": ("Address saved successfully", "Your order is ready for payment", "Track your order"),
        }
        for language, texts in cases.items():
            with self.subTest(language=language):
                prefix = "" if language == "fr" else f"/{language}"
                order.payment_status = "PENDING"
                order.save(update_fields=["payment_status"])
                address_page = self.client.get(f"{prefix}/shop/adresse-enregistree/?order_id={order.pk}")
                self.assertContains(address_page, texts[0])
                order.payment_status = "SUCCESS"
                order.save(update_fields=["payment_status"])
                confirmation = self.client.get(f"{prefix}/shop/confirmation/{order.pk}/")
                history = self.client.get(f"{prefix}/shop/mes-commandes/")
                detail = self.client.get(f"{prefix}/shop/mes-commandes/{order.pk}/")
                self.assertContains(confirmation, texts[1])
                payment_status = {"fr": "Payée", "de": "Bezahlt", "en": "Paid"}[language]
                self.assertContains(history, payment_status)
                self.assertContains(detail, texts[2])
                self.assertContains(detail, "Produit français")

    def test_status_choices_and_shipping_forms_follow_active_language(self):
        order = self._order()
        order.fulfillment_status = "PREPARING"
        for language, expected in {
            "fr": ("Expédiée", "Transporteur", "Indiquez le transporteur."),
            "de": ("Versandt", "Versanddienstleister", "Geben Sie den Versanddienstleister an."),
            "en": ("Shipped", "Carrier", "Enter the carrier."),
        }.items():
            with self.subTest(language=language), translation.override(language):
                transition_form = CommandeTraitementForm(commande=order)
                self.assertIn(expected[0], [str(label) for _value, label in transition_form.fields["statut"].choices])
                form = CommandeExpeditionForm({"carrier": "", "tracking_number": ""}, instance=order)
                self.assertFalse(form.is_valid())
                self.assertEqual(str(form.fields["carrier"].label), expected[1])
                self.assertIn(expected[2], form.errors["carrier"])


class StaffOrderI18nPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user(
            email="staff-i18n@example.com", password="test-password", is_staff=True
        )
        cls.customer = get_user_model().objects.create_user(email="buyer-i18n@example.com")
        cls.address = Adresse.objects.create(
            utilisateur=cls.customer,
            rue="10 Testweg",
            ville="Berlin",
            code_postal="10115",
            pays="Deutschland",
        )
        cls.product = Produit.objects.create(
            nom_fr="Produit staff",
            nom_de="Staff-Produkt",
            nom_en="Staff product",
            slug="staff-product-stable",
            prix=Decimal("25.00"),
        )
        cls.order = Commande.objects.create(
            client=cls.customer,
            adresse=cls.address,
            total=Decimal("25.00"),
            payment_status="SUCCESS",
            payment_channel="STRIPE",
            fulfillment_status="SHIPPED",
            carrier="DHL",
            tracking_number="STAFF-I18N",
        )
        LigneCommande.objects.create(
            commande=cls.order,
            produit=cls.product,
            quantite=1,
            prix_unitaire=cls.product.prix,
        )
        Payment.objects.create(
            commande=cls.order,
            montant=cls.order.total,
            devise="EUR",
            transaction_id="staff-i18n-payment",
            channel="STRIPE",
            status="SUCCESS",
        )

    def setUp(self):
        self.addCleanup(translation.activate, "fr")
        self.client.force_login(self.staff)

    def test_staff_list_detail_and_shipping_form_are_translated(self):
        for language, expected in {
            "fr": ("Gestion des commandes", "Traitement de la commande", "Informations d’expédition"),
            "de": ("Bestellverwaltung", "Bestellabwicklung", "Versandinformationen"),
            "en": ("Order management", "Order fulfillment", "Shipping information"),
        }.items():
            with self.subTest(language=language):
                prefix = "" if language == "fr" else f"/{language}"
                listing = self.client.get(f"{prefix}/shop/commandes/")
                detail = self.client.get(f"{prefix}/shop/commandes/{self.order.pk}/")
                shipping = self.client.get(f"{prefix}/shop/commandes/{self.order.pk}/expedition/")
                self.assertContains(listing, expected[0])
                self.assertContains(detail, expected[1])
                self.assertContains(shipping, expected[2])
                self.assertContains(detail, "Produit staff")
