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
        cls.main_image_only = Produit.objects.create(
            nom="Produit image principale",
            slug="produit-image-principale-ui",
            prix=Decimal("18.00"),
            image="produits/image-principale-seule.jpg",
        )
        cls.secondary_only = Produit.objects.create(
            nom_fr="Produit galerie seule",
            nom_de="Produkt nur mit Galerie",
            nom_en="Gallery-only product",
            slug="produit-galerie-seule-ui",
            prix=Decimal("21.00"),
        )
        cls.secondary_only_image = ProduitImage.objects.create(
            produit=cls.secondary_only,
            image="produits/galerie/image-secondaire-seule.jpg",
            texte_alternatif_fr="Vue secondaire française",
            texte_alternatif_de="Deutsche Sekundäransicht",
            texte_alternatif_en="English secondary view",
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

    def test_gallery_controls_are_localized_in_french_german_and_english(self):
        expectations = (
            (
                f"/shop/produit/{self.product.slug}/",
                "Agrandir l’image",
                "Fermer",
                "Afficher l’image 1 sur 2 de Carnet de voyage premium",
            ),
            (
                f"/de/shop/produit/{self.product.slug}/",
                "Bild vergrößern",
                "Schließen",
                "Bild 1 von 2 für Premium-Reisetagebuch anzeigen",
            ),
            (
                f"/en/shop/produit/{self.product.slug}/",
                "Enlarge image",
                "Close",
                "Display image 1 of 2 of Premium travel notebook",
            ),
        )

        for path, enlarge, close, thumbnail_label in expectations:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertContains(response, f'aria-label="{enlarge}"')
                self.assertContains(response, f"<span>{enlarge}</span>")
                self.assertContains(response, f"<span>{close}</span>")
                self.assertContains(response, f'aria-label="{thumbnail_label}"')

    def test_gallery_alt_text_is_localized_and_falls_back_to_product_name(self):
        expectations = (
            ("fr", "Carnet de voyage premium", "Intérieur du carnet"),
            ("de", "Premium-Reisetagebuch", "Innenseite des Notizbuchs"),
            ("en", "Premium travel notebook", "Inside the notebook"),
        )
        for language, primary_alt, secondary_alt in expectations:
            prefix = "" if language == "fr" else f"/{language}"
            with self.subTest(language=language):
                response = self.client.get(
                    f"{prefix}/shop/produit/{self.product.slug}/"
                )
                self.assertContains(response, f'alt="{primary_alt}"')
                self.assertContains(
                    response,
                    f'data-gallery-alt="{secondary_alt}"',
                )

        fallback_product = Produit.objects.create(
            nom_fr="Nom français de secours",
            nom_de="Deutscher Ersatzname",
            nom_en="English fallback name",
            slug="produit-alt-secours-ui",
            prix=Decimal("14.00"),
        )
        fallback_image = ProduitImage.objects.create(
            produit=fallback_product,
            image="produits/galerie/alt-vide.jpg",
            texte_alternatif_fr="",
            texte_alternatif_de="",
            texte_alternatif_en="",
        )
        response = self.client.get(
            f"/en/shop/produit/{fallback_product.slug}/"
        )
        self.assertContains(response, fallback_image.image.url)
        self.assertContains(response, 'alt="English fallback name"')
        self.assertContains(
            response,
            'data-gallery-alt="English fallback name"',
        )

    def test_gallery_has_real_fallback_links_and_no_positive_tabindex(self):
        response = self.client.get(reverse("shop:detail", args=[self.product.slug]))
        markup = response.content.decode()

        self.assertContains(
            response,
            f'class="product-gallery-enlarge" href="{self.product.image.url}"',
        )
        self.assertContains(
            response,
            f'href="{self.secondary.image.url}" aria-label="Afficher l’image 2 sur 2 de Carnet de voyage premium"',
        )
        self.assertNotIn('href="#"', markup)
        self.assertNotIn("javascript:", markup.lower())
        self.assertNotRegex(markup, r'tabindex="[1-9][0-9]*"')
        self.assertNotRegex(markup, r"<div[^>]+data-gallery-thumbnail")
        self.assertRegex(markup, r'<a[^>]+data-gallery-thumbnail')
        self.assertContains(response, 'aria-current="true"')
        self.assertContains(response, "Image 1 sur 2")
        self.assertRegex(
            markup,
            r'<img alt="" width="1600" height="1600" data-gallery-dialog-image>',
        )

    def test_gallery_handles_main_only_secondary_only_and_no_image(self):
        main_only = self.client.get(
            reverse("shop:detail", args=[self.main_image_only.slug])
        )
        self.assertContains(main_only, "data-gallery-enlarge")
        self.assertContains(main_only, "Image 1 sur 1")
        self.assertContains(main_only, 'aria-current="true"')

        secondary_only = self.client.get(
            f"/en/shop/produit/{self.secondary_only.slug}/"
        )
        self.assertContains(
            secondary_only,
            f'src="{self.secondary_only_image.image.url}" alt="English secondary view" width="1000" height="1000" fetchpriority="high"',
        )
        self.assertContains(
            secondary_only,
            f'href="{self.secondary_only_image.image.url}"',
        )
        self.assertContains(secondary_only, "Image 1 of 1")

        no_image = self.client.get(
            reverse("shop:detail", args=[self.unavailable.slug])
        )
        self.assertContains(no_image, "product-gallery-placeholder")
        self.assertNotContains(no_image, "data-gallery-enlarge")
        self.assertNotContains(no_image, "data-gallery-dialog")

    def test_gallery_keeps_primary_then_secondary_order_by_position_and_pk(self):
        later = ProduitImage.objects.create(
            produit=self.product,
            image="produits/galerie/vue-plus-tard.jpg",
            ordre=5,
        )
        same_position = ProduitImage.objects.create(
            produit=self.product,
            image="produits/galerie/vue-meme-position.jpg",
            ordre=5,
        )

        markup = self.client.get(
            reverse("shop:detail", args=[self.product.slug])
        ).content.decode()
        positions = [
            markup.index(self.product.image.url),
            markup.index(self.secondary.image.url),
            markup.index(later.image.url),
            markup.index(same_position.image.url),
        ]

        self.assertEqual(positions, sorted(positions))
        self.assertIn("Afficher l’image 4 sur 4", markup)

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

    def test_gallery_script_covers_selection_keyboard_dialog_and_focus_return(self):
        for marker in (
            "thumbnail.dataset.gallerySrc",
            "thumbnail.dataset.galleryAlt",
            'setAttribute("aria-current", "true")',
            'event.key === "Escape"',
            'key === "ArrowLeft"',
            'key === "ArrowRight"',
            'key === "Home"',
            'key === "End"',
            'key === "Enter"',
            'key === " "',
            "dialog.showModal()",
            "dialogOpener.focus",
            'addEventListener("click"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.gallery_script)

    def test_gallery_styles_keep_controls_large_visible_and_token_based(self):
        for selector in (
            ".product-gallery-enlarge-label",
            ".product-gallery-dialog-close",
        ):
            rule = re.search(
                rf"{re.escape(selector)}\s*\{{([^}}]*)\}}",
                self.shop_css,
            ).group(1)
            self.assertIn("min-width: 2.75rem", rule)
            self.assertIn("min-height: 2.75rem", rule)

        self.assertIn(".product-gallery-selected", self.shop_css)
        self.assertIn(".product-gallery-dialog::backdrop", self.shop_css)
        self.assertIn(".product-gallery-enlarge:focus-visible", self.shop_css)
