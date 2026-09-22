import re
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation

from .models import Categorie, Produit, ProduitImage


class ShopDocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.headings = []
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag in {"h1", "h2", "h3"}:
            self.headings.append(tag)


class ShopPremiumUIPublicTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Categorie.objects.create(
            nom_fr="Carnets choisis",
            nom_de="Ausgewählte Notizbücher",
            nom_en="Curated notebooks",
            slug="carnets-premium-ui",
        )
        cls.empty_category = Categorie.objects.create(
            nom="Collection vide",
            slug="collection-vide-ui",
        )
        cls.product = Produit.objects.create(
            nom_fr="Carnet de voyage premium",
            nom_de="Premium-Reisetagebuch",
            nom_en="Premium travel notebook",
            description_fr="Un carnet français sélectionné avec soin.",
            description_de="Ein sorgfältig ausgewähltes deutsches Notizbuch.",
            description_en="A carefully selected English notebook.",
            slug="carnet-voyage-premium-ui",
            prix=Decimal("24.90"),
            image="produits/carnet-premium.jpg",
            categorie=cls.category,
            stock=4,
            en_vedette=True,
        )
        cls.secondary = ProduitImage.objects.create(
            produit=cls.product,
            image="produits/galerie/carnet-interieur.jpg",
            texte_alternatif_fr="Intérieur du carnet",
            texte_alternatif_de="Innenseite des Notizbuchs",
            texte_alternatif_en="Inside the notebook",
        )
        cls.unavailable = Produit.objects.create(
            nom="Produit épuisé",
            slug="produit-epuise-premium-ui",
            prix=Decimal("12.00"),
            stock=0,
            categorie=cls.category,
        )

    def setUp(self):
        translation.activate("fr")
        self.addCleanup(translation.activate, "fr")

    def test_public_pages_have_one_h1_and_semantic_landmarks(self):
        paths = (
            reverse("shop:liste"),
            reverse("shop:par_categorie", args=[self.category.slug]),
            reverse("shop:detail", args=[self.product.slug]),
        )
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                parser = ShopDocumentParser()
                parser.feed(response.content.decode())
                self.assertEqual(parser.headings.count("h1"), 1)
                self.assertEqual(parser.headings[0], "h1")
                self.assertIn("nav", parser.tags)
                self.assertIn("section", parser.tags)
                self.assertIn("article", parser.tags)

    def test_category_discovery_only_lists_nonempty_categories_with_counts(self):
        response = self.client.get(reverse("shop:liste"))

        self.assertContains(response, "Carnets choisis")
        self.assertContains(response, f'href="{reverse("shop:par_categorie", args=[self.category.slug])}">Carnets choisis <span>2</span>')
        self.assertNotContains(response, "Collection vide")
        self.assertContains(response, 'aria-current="page">Tous les produits</a>')

    def test_localized_catalog_category_and_detail_content_is_preserved(self):
        expectations = (
            ("/shop/", "Carnet de voyage premium", "Carnets choisis"),
            ("/de/shop/", "Premium-Reisetagebuch", "Ausgewählte Notizbücher"),
            ("/en/shop/", "Premium travel notebook", "Curated notebooks"),
            ("/shop/", "Carnet de voyage premium", "Carnets choisis"),
        )
        for path, product_name, category_name in expectations:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertContains(response, product_name)
                self.assertContains(response, category_name)

        german_detail = self.client.get(
            f"/de/shop/produit/{self.product.slug}/"
        )
        self.assertContains(german_detail, "Premium-Reisetagebuch")
        self.assertContains(german_detail, "Ein sorgfältig ausgewähltes")

    def test_catalog_images_are_sized_lazy_and_keep_localized_alt_text(self):
        response = self.client.get("/en/shop/")

        self.assertContains(
            response,
            f'src="{self.product.image.url}" alt="Premium travel notebook" width="800" height="600" loading="lazy"',
        )
        self.assertContains(response, 'src="/static/images/default.jpg"')
        self.assertContains(response, 'alt="Produit épuisé"')

    def test_detail_gallery_uses_primary_and_localized_secondary_images(self):
        response = self.client.get(
            f"/en/shop/produit/{self.product.slug}/"
        )

        self.assertContains(
            response,
            f'src="{self.product.image.url}" alt="Premium travel notebook" width="1000" height="1000" fetchpriority="high"',
        )
        self.assertContains(response, self.secondary.image.url)
        self.assertContains(response, 'data-gallery-alt="Inside the notebook"')
        self.assertContains(response, "data-product-gallery-main")
        self.assertContains(response, "product-gallery-thumbnail")

    def test_detail_prefetches_gallery_once(self):
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(
                reverse("shop:detail", args=[self.product.slug])
            )

        self.assertEqual(response.status_code, 200)
        gallery_table = ProduitImage._meta.db_table
        gallery_queries = [
            query["sql"]
            for query in captured.captured_queries
            if gallery_table in query["sql"]
        ]
        self.assertEqual(len(gallery_queries), 1)

    def test_stock_states_and_disabled_purchase_controls_are_visible(self):
        response = self.client.get(reverse("shop:liste"))

        self.assertContains(response, "Plus que 4 disponible(s)")
        self.assertContains(response, "Rupture de stock")
        self.assertContains(response, "Indisponible")
        self.assertRegex(
            response.content.decode(),
            rf'action="{re.escape(reverse("shop:ajouter_panier", args=[self.unavailable.slug]))}"[\s\S]*?<button[^>]+disabled aria-disabled="true"',
        )

    def test_database_content_remains_escaped(self):
        unsafe = Produit.objects.create(
            nom_fr="<b>Produit non fiable</b>",
            description_fr="<script>alert('shop')</script> Description.",
            slug="produit-html-premium-ui",
            prix=Decimal("5.00"),
        )

        for response in (
            self.client.get(reverse("shop:liste")),
            self.client.get(reverse("shop:detail", args=[unsafe.slug])),
        ):
            self.assertNotContains(response, "<script>alert")
            self.assertNotContains(response, "<b>Produit")
            self.assertContains(response, "&lt;b&gt;Produit non fiable&lt;/b&gt;")

    def test_empty_catalog_and_empty_category_use_shared_empty_state(self):
        empty_category = self.client.get(
            reverse("shop:par_categorie", args=[self.empty_category.slug])
        )
        self.assertContains(empty_category, 'class="empty-state shop-empty-state"')
        self.assertContains(empty_category, "Aucun produit dans cette catégorie.")

        ProduitImage.objects.all().delete()
        Produit.objects.all().delete()
        empty_catalog = self.client.get(reverse("shop:liste"))
        self.assertContains(empty_catalog, 'class="empty-state shop-empty-state"')
        self.assertContains(empty_catalog, "La sélection arrive bientôt.")


class ShopPremiumUIStaticTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base_dir = Path(settings.BASE_DIR)
        cls.shop_css = (base_dir / "static" / "css" / "shop.css").read_text(
            encoding="utf-8"
        )
        cls.styles_css = (base_dir / "static" / "css" / "styles.css").read_text(
            encoding="utf-8"
        )
        cls.card_template = (
            base_dir / "shop" / "templates" / "shop" / "_product_card.html"
        ).read_text(encoding="utf-8")
        cls.detail_template = (
            base_dir / "shop" / "templates" / "shop" / "detail.html"
        ).read_text(encoding="utf-8")
        cls.gallery_script = (
            base_dir / "static" / "js" / "product-gallery.js"
        ).read_text(encoding="utf-8")

    def test_shop_styles_only_use_foundation_colors(self):
        self.assertNotIn("!important", self.shop_css)
        self.assertIsNone(re.search(r"#[0-9a-f]{3,8}\b", self.shop_css, re.I))
        self.assertIsNone(re.search(r"\brgba?\(", self.shop_css, re.I))

    def test_shop_styles_use_no_undefined_application_variables(self):
        all_css = self.styles_css + "\n" + self.shop_css
        used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", all_css, re.I))
        defined = set(
            re.findall(r"(--[a-z0-9-]+)\s*:\s*[^;{}]+;", all_css, re.I)
        )
        self.assertEqual(used - defined, set())

    def test_static_cards_have_no_implicit_hover_animation(self):
        self.assertNotIn(".shop-card:hover", self.shop_css)
        card_rule = re.search(r"\.shop-card\s*\{([^}]*)\}", self.shop_css).group(1)
        self.assertNotIn("transition", card_rule)
        self.assertNotIn("transform", card_rule)
        self.assertIn(".shop-card-media:hover > img", self.shop_css)

    def test_responsive_focus_and_reduced_motion_guards_are_present(self):
        for marker in (
            "@media (max-width: 1099.98px)",
            "@media (max-width: 991.98px)",
            "@media (max-width: 767.98px)",
            "@media (max-width: 419.98px)",
            "@media (prefers-reduced-motion: reduce)",
            ":focus-visible",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.shop_css)
        self.assertNotIn("overflow-x: hidden", self.shop_css)

    def test_templates_reuse_shared_components_and_keep_escaping(self):
        self.assertIn("surface-card shop-card", self.card_template)
        self.assertIn("badge badge-warning", self.card_template)
        self.assertIn("badge badge-info", self.detail_template)
        self.assertNotRegex(self.card_template, r"\|safe\b")
        self.assertNotRegex(self.detail_template, r"\|safe\b")
        self.assertEqual(self.detail_template.count("<h1"), 1)

    def test_gallery_script_updates_image_alt_and_pressed_state(self):
        for marker in (
            "thumbnail.dataset.gallerySrc",
            "thumbnail.dataset.galleryAlt",
            'setAttribute("aria-pressed"',
            'addEventListener("click"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.gallery_script)
