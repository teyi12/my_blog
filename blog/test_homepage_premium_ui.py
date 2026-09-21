import re
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import translation

from articles.models import Article, CategorieArticle
from shop.models import Categorie, Produit
from videos.models import Video


class HomeDocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.headings = []
        self.images = []
        self.sections = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"h1", "h2", "h3"}:
            self.headings.append(tag)
        if tag == "img":
            self.images.append(attributes)
        if attributes.get("data-home-section"):
            self.sections.append(attributes["data-home-section"])


class HomepagePremiumUITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.article_category = CategorieArticle.objects.create(
            nom_fr="Voyages français",
            nom_de="Deutsche Reisen",
            nom_en="English journeys",
            slug="voyages-home",
        )
        cls.article = Article.objects.create(
            titre_fr="Titre éditorial français",
            titre_de="Deutscher redaktioneller Titel",
            titre_en="English editorial title",
            contenu_fr="Récit français pour la page d’accueil.",
            contenu_de="Deutscher Bericht für die Startseite.",
            contenu_en="English story for the homepage.",
            image_alt_fr="Carnet ouvert près d’une fenêtre",
            image_alt_de="Offenes Notizbuch an einem Fenster",
            image_alt_en="Open notebook beside a window",
            image="articles/home-editorial.jpg",
            slug="article-home-localise",
            categorie=cls.article_category,
            en_vedette=True,
            is_premium=True,
        )
        cls.unsafe_article = Article.objects.create(
            titre_fr="<b>Titre long non fiable</b>",
            titre_de="<b>Langer nicht vertrauenswürdiger Titel</b>",
            titre_en="<b>Long untrusted title</b>",
            contenu_fr="<script>alert('article')</script> contenu",
            contenu_de="<script>alert('artikel')</script> Inhalt",
            contenu_en="<script>alert('article')</script> content",
            image="",
            slug="article-home-echappe",
        )
        cls.video = Video.objects.create(
            titre_fr="Vidéo française publiée",
            titre_de="Veröffentlichtes deutsches Video",
            titre_en="Published English video",
            description_fr="Description vidéo française.",
            description_de="Deutsche Videobeschreibung.",
            description_en="English video description.",
            miniature_alt_fr="Paysage filmé au lever du jour",
            miniature_alt_de="Gefilmte Landschaft bei Tagesanbruch",
            miniature_alt_en="Landscape filmed at daybreak",
            slug="video-home-localisee",
            youtube_url="https://youtu.be/abcdefghijk",
            categorie=cls.article_category,
            est_publie=True,
            en_vedette=True,
        )
        cls.draft_video = Video.objects.create(
            titre_fr="Brouillon confidentiel",
            description_fr="Cette vidéo ne doit pas apparaître.",
            slug="video-home-brouillon",
            youtube_url="https://youtu.be/zyxwvutsrqp",
            est_publie=False,
        )
        cls.product_category = Categorie.objects.create(
            nom_fr="Guides français",
            nom_de="Deutsche Ratgeber",
            nom_en="English guides",
            slug="guides-home",
        )
        cls.product = Produit.objects.create(
            nom_fr="Guide français sélectionné",
            nom_de="Ausgewählter deutscher Ratgeber",
            nom_en="Selected English guide",
            description_fr="Description commerciale française.",
            description_de="Deutsche kommerzielle Beschreibung.",
            description_en="English commercial description.",
            image="produits/home-product.jpg",
            slug="produit-home-localise",
            prix=Decimal("19.90"),
            categorie=cls.product_category,
            en_vedette=True,
        )
        cls.fallback_product = Produit.objects.create(
            nom_fr="Produit français de repli",
            nom_de="",
            nom_en="",
            description_fr="Description française de repli.",
            description_de="",
            description_en="",
            slug="produit-home-repli",
            prix=Decimal("7.50"),
            en_vedette=True,
        )
        cls.unsafe_product = Produit.objects.create(
            nom_fr="Produit HTML",
            nom_de="HTML-Produkt",
            nom_en="HTML product",
            description_fr='<script>alert("fr")</script>',
            description_de='<script>alert("de")</script> Deutsche Beschreibung',
            description_en='<script>alert("en")</script> English description',
            slug="produit-home-html",
            prix=Decimal("2.90"),
            en_vedette=True,
        )

    @staticmethod
    def _path(language):
        return "/" if language == "fr" else f"/{language}/"

    def setUp(self):
        translation.activate("fr")
        self.addCleanup(translation.activate, "fr")

    def test_semantic_structure_has_one_h1_and_ordered_sections(self):
        response = self.client.get("/")
        parser = HomeDocumentParser()
        parser.feed(response.content.decode())

        self.assertEqual(parser.headings.count("h1"), 1)
        self.assertEqual(parser.headings[0], "h1")
        self.assertEqual(
            parser.sections,
            [
                "hero",
                "categories",
                "articles",
                "videos",
                "products",
                "premium",
                "contact",
            ],
        )
        self.assertNotIn(
            ("h1", "h3"),
            list(zip(parser.headings, parser.headings[1:])),
        )

    def test_home_uses_shared_components_and_preserves_public_routes(self):
        response = self.client.get("/")

        for component_class in (
            "surface-card",
            "btn btn-brand",
            "btn btn-soft",
            "badge badge-neutral",
            "badge badge-warning",
        ):
            with self.subTest(component_class=component_class):
                self.assertContains(response, component_class)

        for route in (
            reverse("articles:articles"),
            reverse("articles:article_detail", args=[self.article.slug]),
            reverse("videos:list"),
            reverse("videos:detail", args=[self.video.slug]),
            reverse("shop:liste"),
            reverse("shop:detail", args=[self.product.slug]),
            reverse("monetization:abonnements"),
            reverse("contact"),
        ):
            with self.subTest(route=route):
                self.assertContains(response, f'href="{route}"')

        self.assertNotContains(response, self.draft_video.titre_fr)
        premium_detail = self.client.get(
            reverse("articles:article_detail", args=[self.article.slug])
        )
        self.assertRedirects(
            premium_detail,
            f"{reverse('accounts:login')}?next={reverse('articles:article_detail', args=[self.article.slug])}",
            fetch_redirect_response=False,
        )

    def test_dynamic_content_follows_fr_de_en_and_returns_to_fr(self):
        expected = {
            "fr": (
                "Titre éditorial français",
                "Vidéo française publiée",
                "Guide français sélectionné",
                "Description commerciale française.",
            ),
            "de": (
                "Deutscher redaktioneller Titel",
                "Veröffentlichtes deutsches Video",
                "Ausgewählter deutscher Ratgeber",
                "Deutsche kommerzielle Beschreibung.",
            ),
            "en": (
                "English editorial title",
                "Published English video",
                "Selected English guide",
                "English commercial description.",
            ),
        }

        for language in ("fr", "de", "en", "fr"):
            with self.subTest(language=language):
                response = self.client.get(self._path(language))
                for text in expected[language]:
                    self.assertContains(response, text)
                for other_language, other_values in expected.items():
                    if other_language != language:
                        self.assertNotContains(response, other_values[3])

    def test_product_translation_falls_back_to_french_without_empty_output(self):
        for language in ("de", "en"):
            with self.subTest(language=language):
                response = self.client.get(self._path(language))
                self.assertContains(response, "Produit français de repli")
                self.assertContains(response, "Description française de repli.")

    def test_dynamic_content_remains_html_escaped(self):
        response = self.client.get("/de/")

        self.assertNotContains(response, "<script>alert")
        self.assertNotContains(response, "<b>Langer")
        self.assertContains(response, "&lt;b&gt;Langer nicht vertrauenswürdiger Titel&lt;/b&gt;")
        self.assertContains(
            response,
            "&lt;script&gt;alert(&quot;de&quot;)&lt;/script&gt; Deutsche Beschreibung",
        )

    def test_home_images_have_alt_dimensions_and_loading_strategy(self):
        response = self.client.get("/en/")
        markup = response.content.decode()
        home_markup = markup.split('<div class="home-page">', 1)[1].split(
            "</main>", 1
        )[0]
        parser = HomeDocumentParser()
        parser.feed(home_markup)

        hero_images = [
            image for image in parser.images if image.get("fetchpriority") == "high"
        ]
        self.assertEqual(len(hero_images), 1)
        self.assertNotIn("loading", hero_images[0])
        self.assertEqual(hero_images[0]["width"], "640")
        self.assertEqual(hero_images[0]["height"], "480")

        lazy_images = [image for image in parser.images if image not in hero_images]
        self.assertTrue(lazy_images)
        for image in lazy_images:
            with self.subTest(src=image.get("src")):
                self.assertEqual(image.get("loading"), "lazy")
                self.assertTrue(image.get("alt"))
                self.assertTrue(image.get("width"))
                self.assertTrue(image.get("height"))

        self.assertContains(response, "Open notebook beside a window")
        self.assertContains(response, "Selected English guide")
        self.assertContains(response, "home-media-placeholder")

    def test_authenticated_and_anonymous_home_keep_the_same_content_sections(self):
        anonymous = self.client.get("/")
        user = get_user_model().objects.create_user(
            email="homepage@example.test",
            password="test-password",
        )
        self.client.force_login(user)
        authenticated = self.client.get("/")

        for marker in (
            'data-home-section="articles"',
            'data-home-section="videos"',
            'data-home-section="products"',
            'data-home-section="premium"',
        ):
            with self.subTest(marker=marker):
                self.assertContains(anonymous, marker)
                self.assertContains(authenticated, marker)


class HomepageEmptyAndPartialStateTests(TestCase):
    def setUp(self):
        translation.activate("fr")
        self.addCleanup(translation.activate, "fr")

    def test_no_data_keeps_all_relevant_sections_and_actions(self):
        response = self.client.get("/")

        for text in (
            "Aucun article pour le moment",
            "Aucune vidéo pour le moment",
            "La sélection arrive bientôt.",
        ):
            with self.subTest(text=text):
                self.assertContains(response, text)
        self.assertContains(response, 'class="empty-state home-empty-state"', count=3)

    def test_partial_data_does_not_hide_other_empty_sections(self):
        Article.objects.create(
            titre_fr="Seul contenu disponible",
            contenu_fr="Un accueil volontairement partiel.",
            slug="seul-contenu-home",
            image="",
        )

        response = self.client.get("/")

        self.assertContains(response, "Seul contenu disponible")
        self.assertNotContains(response, "Aucun article pour le moment")
        self.assertContains(response, "Aucune vidéo pour le moment")
        self.assertContains(response, "La sélection arrive bientôt.")


class HomepagePremiumUIStaticTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base_dir = Path(settings.BASE_DIR)
        cls.home_css = (base_dir / "static" / "css" / "home.css").read_text(
            encoding="utf-8"
        )
        cls.styles_css = (base_dir / "static" / "css" / "styles.css").read_text(
            encoding="utf-8"
        )
        cls.home_template = (base_dir / "templates" / "home.html").read_text(
            encoding="utf-8"
        )

    def test_home_css_has_no_important_or_foundation_color_bypass(self):
        self.assertNotIn("!important", self.home_css)
        self.assertIsNone(re.search(r"#[0-9a-f]{3,8}\b", self.home_css, re.I))
        self.assertIsNone(re.search(r"\brgba?\(", self.home_css, re.I))

    def test_home_css_uses_only_defined_application_variables(self):
        all_css = self.styles_css + "\n" + self.home_css
        used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", self.home_css))
        defined = set(
            re.findall(r"(--[a-z0-9-]+)\s*:\s*[^;{}]+;", all_css, re.I)
        )

        self.assertEqual(used - defined, set())

    def test_static_cards_do_not_have_global_hover_lift(self):
        for selector in (
            ".home-editorial-card:hover",
            ".home-video-card:hover",
            ".home-product-card:hover",
        ):
            with self.subTest(selector=selector):
                self.assertNotIn(selector, self.home_css)
        self.assertNotRegex(
            self.home_css,
            r"\.home-(?:editorial|video|product)-card[^{}]*\{[^}]*transform",
        )

    def test_responsive_focus_and_motion_guards_are_present(self):
        for marker in (
            "@media (max-width: 991.98px)",
            "@media (max-width: 767.98px)",
            "@media (max-width: 419.98px)",
            "@media (prefers-reduced-motion: reduce)",
            "transition: none",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.home_css)
        self.assertIn(":focus-visible", self.home_css)
        self.assertNotIn("overflow-x: hidden", self.home_css)

    def test_template_does_not_bypass_escaping_or_duplicate_the_polish_sheet(self):
        self.assertNotRegex(self.home_template, r"\|safe\b")
        self.assertNotIn("home-polish.css", self.home_template)
        self.assertEqual(self.home_template.count("<h1"), 1)
