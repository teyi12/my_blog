from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import translation

from .admin import CategorieAdmin, ProduitAdmin
from .models import Categorie, Produit


class ShopCatalogI18nTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Categorie.objects.create(
            nom="Carnets",
            nom_fr="Carnets",
            nom_de="Notizbücher",
            nom_en="Notebooks",
            slug="carnets",
        )
        cls.product = Produit.objects.create(
            nom="Carnet de voyage",
            nom_fr="Carnet de voyage",
            nom_de="Reisetagebuch",
            nom_en="Travel notebook",
            description="Un carnet français pour vos découvertes.",
            description_fr="Un carnet français pour vos découvertes.",
            description_de="Ein Reisetagebuch für Ihre Entdeckungen.",
            description_en="A travel notebook for your discoveries.",
            slug="carnet-voyage",
            prix=Decimal("19.90"),
            image="produits/catalogue-original.jpg",
            categorie=cls.category,
            en_vedette=True,
        )
        cls.fallback_product = Produit.objects.create(
            nom="Produit uniquement français",
            description="Description uniquement française.",
            slug="produit-francais",
            prix=Decimal("8.50"),
            categorie=cls.category,
        )

    def test_french_catalog_displays_french_dynamic_content(self):
        with translation.override("fr"):
            response = self.client.get(reverse("shop:liste"))

        self.assertContains(response, "Carnet de voyage")
        self.assertContains(response, "Un carnet français pour vos découvertes.")
        self.assertContains(response, "Carnets")
        self.assertContains(response, "Une boutique pensée pour aller à l’essentiel.")

    def test_legacy_fields_auto_populate_at_least_french(self):
        with translation.override("fr"):
            category = Categorie.objects.create(
                nom="Catégorie historique",
                slug="categorie-historique-auto",
            )
            product = Produit.objects.create(
                nom="Produit historique",
                description="Description historique.",
                slug="produit-historique-auto",
                prix=Decimal("3.50"),
                categorie=category,
            )

        category.refresh_from_db()
        product.refresh_from_db()
        self.assertEqual(category.nom_fr, "Catégorie historique")
        self.assertEqual(product.nom_fr, "Produit historique")
        self.assertEqual(product.description_fr, "Description historique.")

    def test_german_catalog_displays_german_dynamic_and_static_content(self):
        response = self.client.get("/de/shop/")

        self.assertContains(response, "Reisetagebuch")
        self.assertContains(response, "Ein Reisetagebuch für Ihre Entdeckungen.")
        self.assertContains(response, "Notizbücher")
        self.assertContains(response, "Ein Shop, der sich auf das Wesentliche konzentriert.")

    def test_english_catalog_displays_english_dynamic_and_static_content(self):
        response = self.client.get("/en/shop/")

        self.assertContains(response, "Travel notebook")
        self.assertContains(response, "A travel notebook for your discoveries.")
        self.assertContains(response, "Notebooks")
        self.assertContains(response, "A shop designed around what matters.")

    def test_german_and_english_fall_back_to_french_dynamic_content(self):
        for path in ("/de/shop/", "/en/shop/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertContains(response, "Produit uniquement français")
                self.assertContains(response, "Description uniquement française.")

    def test_category_and_product_detail_use_the_active_translation(self):
        german_category = self.client.get("/de/shop/categorie/carnets/")
        english_product = self.client.get("/en/shop/produit/carnet-voyage/")

        self.assertContains(german_category, "Notizbücher")
        self.assertContains(german_category, "Reisetagebuch")
        self.assertContains(english_product, "Travel notebook")
        self.assertContains(english_product, "A travel notebook for your discoveries.")

    def test_one_stable_slug_is_used_in_every_language(self):
        with translation.override("fr"):
            french_url = reverse("shop:detail", args=[self.product.slug])
        with translation.override("de"):
            german_url = reverse("shop:detail", args=[self.product.slug])
        with translation.override("en"):
            english_url = reverse("shop:detail", args=[self.product.slug])

        self.assertEqual(french_url, "/shop/produit/carnet-voyage/")
        self.assertEqual(german_url, "/de/shop/produit/carnet-voyage/")
        self.assertEqual(english_url, "/en/shop/produit/carnet-voyage/")
        self.assertEqual(self.product.slug, "carnet-voyage")

    def test_root_and_shop_routes_resolve_in_all_languages(self):
        for path in ("/", "/de/", "/en/", "/shop/", "/de/shop/", "/en/shop/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_image_and_price_are_identical_in_every_language(self):
        for language in ("fr", "de", "en"):
            with self.subTest(language=language), translation.override(language):
                product = Produit.objects.get(pk=self.product.pk)
                self.assertEqual(product.image.name, "produits/catalogue-original.jpg")
                self.assertEqual(product.prix, Decimal("19.90"))

    def test_product_alt_uses_translated_name_and_is_never_empty(self):
        expected = {
            "/shop/": "Carnet de voyage",
            "/de/shop/": "Reisetagebuch",
            "/en/shop/": "Travel notebook",
        }
        for path, alt in expected.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertContains(response, f'alt="{alt}"')
                self.assertNotContains(
                    response,
                    f'src="{self.product.image.url}" alt=""',
                )

        Produit.objects.create(
            nom="",
            nom_fr="",
            nom_de="",
            nom_en="",
            slug="produit-sans-nom",
            prix=Decimal("1.00"),
        )
        response = self.client.get("/en/shop/")
        self.assertContains(response, 'alt="Product image"')
        self.assertNotContains(response, 'images/default.jpg" alt=""')


class ShopTranslationAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_superuser(
            email="catalog-admin@example.com",
            password="test-password",
        )
        cls.category = Categorie.objects.create(
            nom="Papeterie",
            nom_fr="Papeterie",
            nom_de="Schreibwaren",
            nom_en="Stationery",
            slug="papeterie",
        )
        cls.product = Produit.objects.create(
            nom="Stylo plume",
            nom_fr="Stylo plume",
            nom_de="Füllfederhalter",
            nom_en="Fountain pen",
            description="Description française",
            description_fr="Description française",
            description_de="Deutsche Beschreibung",
            description_en="English description",
            slug="stylo-plume",
            prix=Decimal("25.00"),
            categorie=cls.category,
        )

    def _request(self):
        request = RequestFactory().get("/admin/")
        request.user = self.staff
        return request

    def test_admin_exposes_clearly_labelled_translation_fields(self):
        category_form = CategorieAdmin(Categorie, admin.site).get_form(self._request())
        product_form = ProduitAdmin(Produit, admin.site).get_form(self._request())

        self.assertEqual(category_form.base_fields["nom_fr"].label, "Nom [fr]")
        self.assertEqual(category_form.base_fields["nom_de"].label, "Nom [de]")
        self.assertEqual(category_form.base_fields["nom_en"].label, "Nom [en]")
        self.assertEqual(product_form.base_fields["description_fr"].label, "Description [fr]")
        self.assertEqual(product_form.base_fields["description_de"].label, "Description [de]")
        self.assertEqual(product_form.base_fields["description_en"].label, "Description [en]")
        self.assertIn("image", product_form.base_fields)
        self.assertIn("fichier", product_form.base_fields)
        self.assertIn("categorie", product_form.base_fields)
        self.assertIn("prix", product_form.base_fields)
        self.assertIn("en_vedette", product_form.base_fields)

    def test_admin_search_finds_category_and_product_in_all_languages(self):
        self.client.force_login(self.staff)

        for query in ("Papeterie", "Schreibwaren", "Stationery"):
            with self.subTest(model="category", query=query):
                response = self.client.get(
                    reverse("admin:shop_categorie_changelist"), {"q": query}
                )
                self.assertContains(response, "Papeterie")

        for query in ("Stylo plume", "Füllfederhalter", "Fountain pen"):
            with self.subTest(model="product", query=query):
                response = self.client.get(
                    reverse("admin:shop_produit_changelist"), {"q": query}
                )
                self.assertContains(response, "Stylo plume")
