import re
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone, translation

from monetization.models import Abonnement, AbonnementUtilisateur

from .models import Article, ArticleMedia, CategorieArticle


class ArticleDocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.headings = []
        self.images = []
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag in {"h1", "h2", "h3"}:
            self.headings.append(tag)
        if tag == "img":
            self.images.append(dict(attrs))


class ArticlePremiumUIPublicTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.free_user = User.objects.create_user(
            email="articles-ui-free@example.test",
            password="test-password",
        )
        cls.subscriber = User.objects.create_user(
            email="articles-ui-subscriber@example.test",
            password="test-password",
        )
        cls.expired_user = User.objects.create_user(
            email="articles-ui-expired@example.test",
            password="test-password",
        )
        cls.staff = User.objects.create_user(
            email="articles-ui-staff@example.test",
            password="test-password",
            is_staff=True,
        )
        cls.superuser = User.objects.create_superuser(
            email="articles-ui-superuser@example.test",
            password="test-password",
        )
        plan = Abonnement.objects.create(
            nom="Premium articles UI",
            prix="9.99",
            duree_jours=30,
            description="Accès aux contenus éditoriaux.",
        )
        now = timezone.now()
        AbonnementUtilisateur.objects.create(
            utilisateur=cls.subscriber,
            abonnement=plan,
            date_fin=now + timedelta(days=30),
            actif=True,
        )
        AbonnementUtilisateur.objects.create(
            utilisateur=cls.expired_user,
            abonnement=plan,
            date_fin=now - timedelta(seconds=1),
            actif=True,
        )
        cls.category = CategorieArticle.objects.create(
            nom_fr="Culture française",
            nom_de="Deutsche Kultur",
            nom_en="English culture",
            slug="culture-articles-ui",
        )
        cls.public_article = Article.objects.create(
            titre_fr="Récit public français",
            titre_de="Öffentlicher deutscher Bericht",
            titre_en="Public English story",
            contenu_fr="Contenu public français pour la carte.",
            contenu_de="Öffentlicher deutscher Inhalt für die Karte.",
            contenu_en="Public English content for the card.",
            image_alt_fr="Carnet public sur une table",
            image_alt_de="Öffentliches Notizbuch auf einem Tisch",
            image_alt_en="Public notebook on a table",
            image="articles/public-editorial.jpg",
            slug="recit-public-ui",
            categorie=cls.category,
        )
        cls.premium_article = Article.objects.create(
            titre_fr="Dossier Premium visible",
            titre_de="Sichtbares Premium-Dossier",
            titre_en="Visible Premium feature",
            contenu_fr="SECRET-PREMIUM-FR réservé aux abonnés.",
            contenu_de="SECRET-PREMIUM-DE nur für Abonnenten.",
            contenu_en="SECRET-PREMIUM-EN for subscribers only.",
            image_alt_fr="IMAGE-ALT-PREMIUM-SECRETE",
            image_alt_de="GEHEIMER-PREMIUM-ALTTEXT",
            image_alt_en="SECRET-PREMIUM-ALT-TEXT",
            image="articles/premium-secret.jpg",
            slug="dossier-premium-ui",
            categorie=cls.category,
            en_vedette=True,
            is_premium=True,
        )
        cls.no_image_article = Article.objects.create(
            titre_fr="Article sans image",
            contenu_fr="Contenu compatible sans image.",
            image="",
            slug="article-sans-image-ui",
        )
        cls.unsafe_article = Article.objects.create(
            titre_fr="<b>Titre non fiable</b>",
            titre_de="<b>Nicht vertrauenswürdiger Titel</b>",
            titre_en="<b>Untrusted title</b>",
            contenu_fr="<script>alert('fr')</script> Texte français.",
            contenu_de="<script>alert('de')</script> Deutscher Text.",
            contenu_en="<script>alert('en')</script> English text.",
            image="",
            slug="article-html-ui",
        )

    def setUp(self):
        translation.activate("fr")
        self.addCleanup(translation.activate, "fr")

    @staticmethod
    def _path(language, slug=None):
        prefix = "" if language == "fr" else f"/{language}"
        suffix = f"{slug}/" if slug else ""
        return f"{prefix}/articles/{suffix}"

    def test_list_and_detail_have_semantic_heading_structure(self):
        for path in (
            reverse("articles:articles"),
            reverse("articles:article_detail", args=[self.public_article.slug]),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                parser = ArticleDocumentParser()
                parser.feed(response.content.decode())

                self.assertEqual(parser.headings.count("h1"), 1)
                self.assertEqual(parser.headings[0], "h1")
                self.assertIn("article", parser.tags)
                self.assertIn("nav", parser.tags)
        detail_parser = ArticleDocumentParser()
        detail_parser.feed(
            self.client.get(
                reverse("articles:article_detail", args=[self.public_article.slug])
            ).content.decode()
        )
        self.assertIn("aside", detail_parser.tags)

    def test_locked_premium_card_never_exposes_excerpt_or_media_attributes(self):
        response = self.client.get(reverse("articles:articles"))

        self.assertContains(response, self.premium_article.titre_fr)
        self.assertContains(response, "Cet article est réservé aux abonnés.")
        self.assertContains(response, "Accès Premium")
        self.assertContains(response, "article-locked-media")
        self.assertNotContains(response, "SECRET-PREMIUM-FR")
        self.assertNotContains(response, self.premium_article.image.url)
        self.assertNotContains(response, "IMAGE-ALT-PREMIUM-SECRETE")

    def test_free_and_expired_users_keep_premium_card_locked(self):
        for user in (self.free_user, self.expired_user):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(reverse("articles:articles"))
                self.assertNotContains(response, "SECRET-PREMIUM-FR")
                self.assertNotContains(response, self.premium_article.image.url)
                self.assertContains(response, "article-locked-media")
                self.client.logout()

    def test_subscriber_staff_and_superuser_receive_premium_preview(self):
        for user in (self.subscriber, self.staff, self.superuser):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(reverse("articles:articles"))
                self.assertContains(response, "SECRET-PREMIUM-FR")
                self.assertContains(response, self.premium_article.image.url)
                self.assertContains(response, "IMAGE-ALT-PREMIUM-SECRETE")
                self.client.logout()

    def test_premium_detail_access_redirects_and_next_are_unchanged(self):
        detail_url = reverse(
            "articles:article_detail", args=[self.premium_article.slug]
        )
        anonymous = self.client.get(detail_url)
        self.assertRedirects(
            anonymous,
            f"{reverse('accounts:login')}?next={detail_url}",
        )
        self.assertNotContains(anonymous, "SECRET-PREMIUM-FR", status_code=302)
        self.assertNotContains(anonymous, '<meta property="og:', status_code=302)

        for user in (self.free_user, self.expired_user):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(detail_url)
                self.assertRedirects(response, reverse("monetization:abonnements"))
                self.assertNotContains(
                    response,
                    "SECRET-PREMIUM-FR",
                    status_code=302,
                )
                self.client.logout()

        for user in (self.subscriber, self.staff, self.superuser):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(detail_url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "SECRET-PREMIUM-FR")
                self.assertContains(response, 'content="SECRET-PREMIUM-FR')
                self.client.logout()

    def test_localized_content_and_french_fallback_survive_successive_languages(self):
        expected = (
            ("fr", "Récit public français", "Contenu public français"),
            ("de", "Öffentlicher deutscher Bericht", "Öffentlicher deutscher Inhalt"),
            ("en", "Public English story", "Public English content"),
            ("fr", "Récit public français", "Contenu public français"),
        )
        for language, title, content in expected:
            with self.subTest(language=language):
                response = self.client.get(self._path(language))
                self.assertContains(response, title)
                self.assertContains(response, content)

        for language in ("de", "en"):
            with self.subTest(fallback=language):
                response = self.client.get(
                    self._path(language, self.no_image_article.slug)
                )
                self.assertContains(response, "Article sans image")
                self.assertContains(response, "Contenu compatible sans image.")

    def test_database_content_remains_escaped_in_list_detail_and_attributes(self):
        list_response = self.client.get("/de/articles/")
        detail_response = self.client.get("/de/articles/article-html-ui/")

        for response in (list_response, detail_response):
            self.assertNotContains(response, "<script>alert")
            self.assertNotContains(response, "<b>Nicht")
            self.assertContains(
                response,
                "&lt;b&gt;Nicht vertrauenswürdiger Titel&lt;/b&gt;",
            )

    def test_image_loading_dimensions_alt_and_missing_image_placeholder(self):
        list_response = self.client.get(reverse("articles:articles"))
        detail_response = self.client.get(
            reverse("articles:article_detail", args=[self.public_article.slug])
        )

        self.assertContains(
            list_response,
            f'src="{self.public_article.image.url}" alt="Carnet public sur une table" width="800" height="500" loading="lazy"',
        )
        self.assertContains(
            detail_response,
            f'src="{self.public_article.image.url}" alt="Carnet public sur une table" width="1280" height="672" fetchpriority="high"',
        )
        detail_markup = detail_response.content.decode()
        hero_tag = re.search(
            rf'<img src="{re.escape(self.public_article.image.url)}"[^>]+>',
            detail_markup,
        ).group(0)
        self.assertNotIn('loading="lazy"', hero_tag)

        no_image = self.client.get(
            reverse("articles:article_detail", args=[self.no_image_article.slug])
        )
        self.assertContains(no_image, "article-detail-placeholder")
        self.assertNotContains(no_image, 'src="/static/images/default.jpg"')

    def test_sponsored_secondary_media_is_lazy_and_sized(self):
        sponsored = Article.objects.create(
            titre="Article sponsorisé avec média",
            contenu="Contenu sponsorisé public.",
            slug="article-sponsorise-media-ui",
            est_sponsorise=True,
        )
        media = ArticleMedia.objects.create(
            article=sponsored,
            type="image",
            fichier="medias/sponsor-editorial.jpg",
        )

        response = self.client.get(
            reverse("articles:article_detail", args=[sponsored.slug])
        )

        self.assertContains(response, media.fichier.url)
        self.assertContains(response, 'width="1200" height="675" loading="lazy"')
        self.assertContains(response, 'width="800" height="600" loading="lazy"')

    def test_unknown_article_remains_404_and_public_routes_remain_gettable(self):
        self.assertEqual(self.client.get("/articles/inconnu-ui/").status_code, 404)
        self.assertEqual(self.client.get(reverse("articles:articles")).status_code, 200)
        self.assertEqual(
            self.client.get(
                reverse("articles:article_detail", args=[self.public_article.slug])
            ).status_code,
            200,
        )


class ArticlePremiumUIListStateTests(TestCase):
    def setUp(self):
        translation.activate("fr")
        self.addCleanup(translation.activate, "fr")

    def test_empty_list_uses_shared_empty_state(self):
        response = self.client.get(reverse("articles:articles"))

        self.assertContains(response, 'class="empty-state articles-empty"')
        self.assertContains(response, "Aucun article pour le moment")
        self.assertContains(response, "Les prochains récits et découvertes apparaîtront ici.")

    def test_single_article_has_no_empty_state(self):
        Article.objects.create(
            titre="Publication unique",
            contenu="Un seul contenu éditorial.",
            image="",
            slug="publication-unique-ui",
        )

        response = self.client.get(reverse("articles:articles"))

        self.assertContains(response, "Publication unique")
        self.assertNotContains(response, "Aucun article pour le moment")

    def test_existing_pagination_routes_and_page_parameter_are_preserved(self):
        for index in range(7):
            Article.objects.create(
                titre=f"Article pagination {index}",
                contenu=f"Contenu pagination {index}",
                slug=f"article-pagination-ui-{index}",
            )

        first_page = self.client.get(reverse("articles:articles"))
        second_page = self.client.get(reverse("articles:articles"), {"page": 2})

        self.assertTrue(first_page.context["page_obj"].has_next())
        self.assertContains(first_page, "?page=2")
        self.assertEqual(second_page.context["page_obj"].number, 2)
        self.assertContains(second_page, "?page=1")
        self.assertContains(second_page, 'aria-current="page">2</span>')


class ArticlePremiumUIStaticTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base_dir = Path(settings.BASE_DIR)
        cls.list_css = (base_dir / "static" / "css" / "articles.css").read_text(
            encoding="utf-8"
        )
        cls.detail_css = (
            base_dir / "static" / "css" / "article-detail.css"
        ).read_text(encoding="utf-8")
        cls.styles_css = (base_dir / "static" / "css" / "styles.css").read_text(
            encoding="utf-8"
        )
        cls.card_template = (
            base_dir / "articles" / "templates" / "articles" / "_article_card.html"
        ).read_text(encoding="utf-8")
        cls.detail_template = (
            base_dir / "articles" / "templates" / "articles" / "detail.html"
        ).read_text(encoding="utf-8")

    def test_article_styles_only_use_foundation_colors(self):
        article_css = self.list_css + "\n" + self.detail_css
        self.assertNotIn("!important", article_css)
        self.assertIsNone(re.search(r"#[0-9a-f]{3,8}\b", article_css, re.I))
        self.assertIsNone(re.search(r"\brgba?\(", article_css, re.I))

    def test_article_styles_use_no_undefined_application_variables(self):
        all_css = self.styles_css + "\n" + self.list_css + "\n" + self.detail_css
        used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", all_css, re.I))
        defined = set(
            re.findall(r"(--[a-z0-9-]+)\s*:\s*[^;{}]+;", all_css, re.I)
        )
        self.assertEqual(used - defined, set())

    def test_static_cards_have_no_hover_animation(self):
        self.assertNotIn(".article-card:hover", self.list_css)
        card_rule = re.search(r"\.article-card\s*\{([^}]*)\}", self.list_css).group(1)
        self.assertNotIn("transition", card_rule)
        self.assertNotIn("transform", card_rule)
        self.assertIn(".article-card-media:hover img", self.list_css)

    def test_responsive_focus_and_reduced_motion_guards_are_present(self):
        combined = self.list_css + "\n" + self.detail_css
        for marker in (
            "@media (max-width: 1099.98px)",
            "@media (max-width: 991.98px)",
            "@media (max-width: 767.98px)",
            "@media (max-width: 419.98px)",
            "@media (prefers-reduced-motion: reduce)",
            ":focus-visible",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, combined)
        self.assertNotIn("overflow-x: hidden", combined)

    def test_long_content_media_tables_and_code_are_width_constrained(self):
        for marker in (
            ".article-body iframe",
            ".article-body table",
            ".article-body pre",
            "max-width: 100%",
            "overflow-x: auto",
            "overflow-wrap: anywhere",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.detail_css)

    def test_templates_reuse_shared_components_and_keep_escaping(self):
        self.assertIn("surface-card article-card", self.card_template)
        self.assertIn("badge badge-warning", self.card_template)
        self.assertIn("surface-card article-side-note", self.detail_template)
        self.assertNotRegex(self.card_template, r"\|safe\b")
        self.assertNotRegex(self.detail_template, r"\|safe\b")
        self.assertEqual(self.detail_template.count("<h1"), 1)
