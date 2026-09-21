from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from .forms import ProduitForm
from .models import Cart, CartItem, Categorie, Produit


class ProductDescriptionLocalizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="product-language@example.com",
            password="test-password",
        )
        cls.category = Categorie.objects.create(
            nom_fr="Guides français",
            nom_de="Deutsche Ratgeber",
            nom_en="English guides",
            slug="guides-localized",
        )
        cls.product = Produit.objects.create(
            nom_fr="Guide français exclusif",
            nom_de="Exklusiver deutscher Ratgeber",
            nom_en="Exclusive English guide",
            description_fr="Description source uniquement française.",
            description_de="Eindeutig deutsche Produktbeschreibung.",
            description_en="Distinctly English product description.",
            slug="guide-localized",
            prix=Decimal("14.90"),
            categorie=cls.category,
            en_vedette=True,
        )
        cls.fallback_product = Produit.objects.create(
            nom_fr="Produit français de repli",
            nom_de="",
            nom_en="",
            description_fr="Description française de repli visible.",
            description_de="",
            description_en="   ",
            slug="produit-description-repli",
            prix=Decimal("4.90"),
            categorie=cls.category,
        )
        cls.html_product = Produit.objects.create(
            nom_fr="Produit HTML",
            nom_de="HTML-Produkt",
            nom_en="HTML product",
            description_fr='<script>alert("fr")</script>',
            description_de='<script>alert("de")</script> Deutsche Beschreibung',
            description_en='<script>alert("en")</script> English description',
            slug="produit-html",
            prix=Decimal("2.90"),
            categorie=cls.category,
        )

    def setUp(self):
        self.addCleanup(translation.activate, "fr")

    @staticmethod
    def _path(language, suffix):
        prefix = "" if language == "fr" else f"/{language}"
        return f"{prefix}{suffix}"

    def test_explicit_product_properties_follow_fr_de_en_and_return_to_fr(self):
        expected = {
            "fr": (
                "Guide français exclusif",
                "Description source uniquement française.",
            ),
            "de": (
                "Exklusiver deutscher Ratgeber",
                "Eindeutig deutsche Produktbeschreibung.",
            ),
            "en": (
                "Exclusive English guide",
                "Distinctly English product description.",
            ),
        }

        for language in ("fr", "de", "en", "fr"):
            with self.subTest(language=language), translation.override(language):
                self.assertEqual(
                    self.product.localized_name,
                    expected[language][0],
                )
                self.assertEqual(
                    self.product.localized_description,
                    expected[language][1],
                )

    def test_list_and_detail_display_only_the_target_translation(self):
        expected = {
            "fr": (
                "Guide français exclusif",
                "Description source uniquement française.",
            ),
            "de": (
                "Exklusiver deutscher Ratgeber",
                "Eindeutig deutsche Produktbeschreibung.",
            ),
            "en": (
                "Exclusive English guide",
                "Distinctly English product description.",
            ),
        }

        for language, (name, description) in expected.items():
            with self.subTest(language=language):
                list_response = self.client.get(self._path(language, "/shop/"))
                detail_response = self.client.get(
                    self._path(language, "/shop/produit/guide-localized/")
                )
                for response in (list_response, detail_response):
                    self.assertContains(response, name)
                    self.assertContains(response, description)
                    if language != "fr":
                        self.assertNotContains(
                            response,
                            "Description source uniquement française.",
                        )

    def test_home_and_category_pages_use_the_same_product_translation(self):
        home = self.client.get("/de/")
        category = self.client.get("/en/shop/categorie/guides-localized/")

        self.assertContains(home, "Eindeutig deutsche Produktbeschreibung.")
        self.assertNotContains(home, "Description source uniquement française.")
        self.assertContains(category, "Distinctly English product description.")
        self.assertNotContains(category, "Description source uniquement française.")

    def test_empty_german_and_english_values_fall_back_to_french(self):
        for language in ("de", "en"):
            with self.subTest(language=language):
                response = self.client.get(
                    self._path(
                        language,
                        "/shop/produit/produit-description-repli/",
                    )
                )
                self.assertContains(response, "Produit français de repli")
                self.assertContains(
                    response,
                    "Description française de repli visible.",
                )

    def test_cart_and_checkout_localize_names_without_exposing_descriptions(self):
        self.client.force_login(self.user)
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(
            cart=cart,
            produit=self.product,
            quantite=1,
            prix_unitaire=self.product.prix,
        )

        for language, expected_name in (
            ("de", "Exklusiver deutscher Ratgeber"),
            ("en", "Exclusive English guide"),
        ):
            with self.subTest(language=language):
                cart_response = self.client.get(
                    self._path(language, "/shop/panier/")
                )
                checkout_response = self.client.get(
                    self._path(language, "/shop/checkout/")
                )
                for response in (cart_response, checkout_response):
                    self.assertContains(response, expected_name)
                    self.assertNotContains(
                        response,
                        "Description source uniquement française.",
                    )
                    self.assertNotContains(
                        response,
                        "Eindeutig deutsche Produktbeschreibung.",
                    )
                    self.assertNotContains(
                        response,
                        "Distinctly English product description.",
                    )

    def test_description_keeps_django_html_escaping(self):
        response = self.client.get("/de/shop/produit/produit-html/")

        self.assertContains(
            response,
            "&lt;script&gt;alert(&quot;de&quot;)&lt;/script&gt;",
        )
        self.assertNotContains(response, "<script>alert")
        self.assertContains(response, "Deutsche Beschreibung")

    def test_same_client_can_switch_fr_de_en_fr_without_stale_content(self):
        path = "/shop/produit/guide-localized/"
        expected = (
            ("fr", "Description source uniquement française."),
            ("de", "Eindeutig deutsche Produktbeschreibung."),
            ("en", "Distinctly English product description."),
            ("fr", "Description source uniquement française."),
        )

        for language, description in expected:
            with self.subTest(language=language):
                switch_response = self.client.post(
                    reverse("set_language"),
                    {"language": language, "next": path},
                )
                self.assertEqual(switch_response.status_code, 302)
                path = switch_response.url
                page = self.client.get(path)
                self.assertEqual(page.wsgi_request.LANGUAGE_CODE, language)
                self.assertContains(page, description)

    def test_existing_legacy_product_keeps_its_french_content_as_fallback(self):
        with translation.override("fr"):
            legacy_product = Produit.objects.create(
                nom="Produit existant",
                description="Description existante.",
                slug="produit-existant-compatible",
                prix=Decimal("3.90"),
            )

        legacy_product.refresh_from_db()
        self.assertEqual(legacy_product.nom_fr, "Produit existant")
        self.assertEqual(legacy_product.description_fr, "Description existante.")
        for language in ("de", "en"):
            with self.subTest(language=language), translation.override(language):
                self.assertEqual(legacy_product.localized_name, "Produit existant")
                self.assertEqual(
                    legacy_product.localized_description,
                    "Description existante.",
                )

    def test_product_form_exposes_all_languages_and_requires_french_name(self):
        form = ProduitForm()

        for field_name in (
            "nom_fr",
            "nom_de",
            "nom_en",
            "description_fr",
            "description_de",
            "description_en",
        ):
            with self.subTest(field_name=field_name):
                self.assertIn(field_name, form.fields)
        self.assertTrue(form.fields["nom_fr"].required)
        self.assertFalse(form.fields["nom_de"].required)
        self.assertFalse(form.fields["nom_en"].required)

        bound_form = ProduitForm(
            {
                "nom_fr": "Produit saisi en français",
                "nom_de": "Auf Deutsch erfasstes Produkt",
                "nom_en": "Product entered in English",
                "description_fr": "Description saisie en français.",
                "description_de": "Auf Deutsch erfasste Beschreibung.",
                "description_en": "Description entered in English.",
                "prix": "7.90",
            }
        )
        self.assertTrue(bound_form.is_valid(), bound_form.errors)
        saved_product = bound_form.save()
        self.assertEqual(saved_product.nom_fr, "Produit saisi en français")
        self.assertEqual(
            saved_product.localized_description_for("de"),
            "Auf Deutsch erfasste Beschreibung.",
        )
