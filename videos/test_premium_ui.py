import re
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone, translation

from articles.models import CategorieArticle
from monetization.models import Abonnement, AbonnementUtilisateur

from .models import Video


PUBLIC_YOUTUBE_ID = "dQw4w9WgXcQ"
PREMIUM_YOUTUBE_ID = "aqz-KE-bpKQ"


class VideoDocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.headings = []
        self.tags = []
        self.iframes = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag in {"h1", "h2", "h3"}:
            self.headings.append(tag)
        if tag == "iframe":
            self.iframes.append(dict(attrs))


class VideoPremiumUIPublicTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.free_user = User.objects.create_user(
            email="videos-ui-free@example.test",
            password="test-password",
        )
        cls.subscriber = User.objects.create_user(
            email="videos-ui-subscriber@example.test",
            password="test-password",
        )
        cls.expired_user = User.objects.create_user(
            email="videos-ui-expired@example.test",
            password="test-password",
        )
        cls.staff = User.objects.create_user(
            email="videos-ui-staff@example.test",
            password="test-password",
            is_staff=True,
        )
        cls.superuser = User.objects.create_superuser(
            email="videos-ui-superuser@example.test",
            password="test-password",
        )
        plan = Abonnement.objects.create(
            nom="Premium vidéos UI",
            prix="9.99",
            duree_jours=30,
            description="Accès aux contenus vidéo.",
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
            nom_fr="Carnets vidéo",
            nom_de="Videotagebücher",
            nom_en="Video journals",
            slug="carnets-video-ui",
        )
        cls.public_video = Video.objects.create(
            titre_fr="Récit vidéo public",
            titre_de="Öffentliche Videogeschichte",
            titre_en="Public video story",
            description_fr="Description publique française de la vidéo.",
            description_de="Öffentliche deutsche Videobeschreibung.",
            description_en="Public English video description.",
            youtube_url=f"https://youtu.be/{PUBLIC_YOUTUBE_ID}",
            miniature="videos/thumbnails/public-editorial.jpg",
            miniature_alt_fr="Paysage public filmé",
            miniature_alt_de="Öffentlich gefilmte Landschaft",
            miniature_alt_en="Public filmed landscape",
            slug="recit-video-public-ui",
            categorie=cls.category,
            est_publie=True,
        )
        cls.premium_video = Video.objects.create(
            titre_fr="Vidéo Premium visible",
            titre_de="Sichtbares Premium-Video",
            titre_en="Visible Premium video",
            description_fr="SECRET-VIDEO-PREMIUM-FR réservé aux abonnés.",
            description_de="SECRET-VIDEO-PREMIUM-DE nur für Abonnenten.",
            description_en="SECRET-VIDEO-PREMIUM-EN for subscribers only.",
            youtube_url=f"https://www.youtube.com/watch?v={PREMIUM_YOUTUBE_ID}",
            miniature="videos/thumbnails/premium-secret.jpg",
            miniature_alt_fr="MINIATURE-PREMIUM-SECRETE",
            miniature_alt_de="GEHEIME-PREMIUM-MINIATUR",
            miniature_alt_en="SECRET-PREMIUM-THUMBNAIL",
            slug="video-premium-ui",
            categorie=cls.category,
            est_publie=True,
            en_vedette=True,
            is_premium=True,
        )
        cls.draft = Video.objects.create(
            titre_fr="BROUILLON-VIDEO-SECRET",
            description_fr="DESCRIPTION-BROUILLON-SECRETE",
            youtube_url=f"https://youtu.be/{PUBLIC_YOUTUBE_ID}",
            slug="brouillon-video-ui",
            est_publie=False,
        )
        cls.fallback_video = Video.objects.create(
            titre_fr="Vidéo française de secours",
            titre_de="",
            titre_en="",
            description_fr="Description française de secours.",
            description_de="",
            description_en="",
            youtube_url=f"https://youtu.be/{PUBLIC_YOUTUBE_ID}",
            slug="video-francaise-secours-ui",
            est_publie=True,
        )
        cls.unsafe_video = Video.objects.create(
            titre_fr="<b>Titre vidéo non fiable</b>",
            titre_de="<b>Nicht vertrauenswürdiger Videotitel</b>",
            titre_en="<b>Untrusted video title</b>",
            description_fr="<script>alert('fr')</script> Description française.",
            description_de="<script>alert('de')</script> Deutsche Beschreibung.",
            description_en="<script>alert('en')</script> English description.",
            youtube_url=f"https://youtu.be/{PUBLIC_YOUTUBE_ID}",
            slug="video-html-ui",
            est_publie=True,
        )

    def setUp(self):
        translation.activate("fr")
        self.addCleanup(translation.activate, "fr")

    @staticmethod
    def _path(language, slug=None):
        prefix = "" if language == "fr" else f"/{language}"
        suffix = f"{slug}/" if slug else ""
        return f"{prefix}/videos/{suffix}"

    def test_list_and_detail_have_semantic_heading_structure(self):
        for path in (
            reverse("videos:list"),
            reverse("videos:detail", args=[self.public_video.slug]),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                parser = VideoDocumentParser()
                parser.feed(response.content.decode())
                self.assertEqual(parser.headings.count("h1"), 1)
                self.assertEqual(parser.headings[0], "h1")
                self.assertIn("nav", parser.tags)
                self.assertIn("article", parser.tags)
                self.assertIn("section", parser.tags)

    def test_only_published_videos_are_public(self):
        response = self.client.get(reverse("videos:list"))
        self.assertNotContains(response, "BROUILLON-VIDEO-SECRET")
        self.assertNotContains(response, "DESCRIPTION-BROUILLON-SECRETE")
        self.assertEqual(
            self.client.get(
                reverse("videos:detail", args=[self.draft.slug])
            ).status_code,
            404,
        )

    def test_locked_card_exposes_no_private_description_thumbnail_or_provider(self):
        response = self.client.get(reverse("videos:list"))
        self.assertContains(response, self.premium_video.titre_fr)
        self.assertContains(response, "Cette vidéo est réservée aux abonnés.")
        self.assertContains(response, "Accès Premium")
        self.assertContains(response, "video-locked-media")
        self.assertNotContains(response, "SECRET-VIDEO-PREMIUM-FR")
        self.assertNotContains(response, self.premium_video.miniature.url)
        self.assertNotContains(response, "MINIATURE-PREMIUM-SECRETE")
        self.assertNotContains(response, PREMIUM_YOUTUBE_ID)
        self.assertNotContains(response, "youtube-nocookie.com")

    def test_free_and_expired_users_keep_premium_card_locked(self):
        for user in (self.free_user, self.expired_user):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(reverse("videos:list"))
                self.assertNotContains(response, "SECRET-VIDEO-PREMIUM-FR")
                self.assertNotContains(response, self.premium_video.miniature.url)
                self.assertContains(response, "video-locked-media")
                self.client.logout()

    def test_subscriber_staff_and_superuser_receive_premium_preview(self):
        for user in (self.subscriber, self.staff, self.superuser):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(reverse("videos:list"))
                self.assertContains(response, "SECRET-VIDEO-PREMIUM-FR")
                self.assertContains(response, self.premium_video.miniature.url)
                self.assertContains(response, "MINIATURE-PREMIUM-SECRETE")
                self.client.logout()

    def test_premium_detail_redirects_and_never_loads_provider_when_locked(self):
        detail_url = reverse("videos:detail", args=[self.premium_video.slug])
        anonymous = self.client.get(detail_url)
        self.assertRedirects(
            anonymous,
            f"{reverse('accounts:login')}?next={detail_url}",
        )
        for forbidden in (
            "SECRET-VIDEO-PREMIUM-FR",
            PREMIUM_YOUTUBE_ID,
            "youtube.com",
            "youtube-nocookie.com",
            '<meta property="og:',
        ):
            self.assertNotContains(anonymous, forbidden, status_code=302)

        for user in (self.free_user, self.expired_user):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(detail_url)
                self.assertRedirects(response, reverse("monetization:abonnements"))
                self.assertNotContains(
                    response,
                    PREMIUM_YOUTUBE_ID,
                    status_code=302,
                )
                self.client.logout()

    def test_authorized_users_keep_existing_player_access(self):
        detail_url = reverse("videos:detail", args=[self.premium_video.slug])
        for user in (self.subscriber, self.staff, self.superuser):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(detail_url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "SECRET-VIDEO-PREMIUM-FR")
                self.assertContains(
                    response,
                    f"https://www.youtube-nocookie.com/embed/{PREMIUM_YOUTUBE_ID}",
                )
                self.client.logout()

    def test_localized_content_and_fallback_survive_successive_languages(self):
        expected = (
            ("fr", "Récit vidéo public", "Description publique française"),
            ("de", "Öffentliche Videogeschichte", "Öffentliche deutsche"),
            ("en", "Public video story", "Public English"),
            ("fr", "Récit vidéo public", "Description publique française"),
        )
        for language, title, description in expected:
            with self.subTest(language=language):
                response = self.client.get(self._path(language))
                self.assertContains(response, title)
                self.assertContains(response, description)

        for language in ("de", "en"):
            with self.subTest(fallback=language):
                response = self.client.get(
                    self._path(language, self.fallback_video.slug)
                )
                self.assertContains(response, "Vidéo française de secours")
                self.assertContains(response, "Description française de secours.")

    def test_database_content_remains_escaped(self):
        for response in (
            self.client.get("/de/videos/"),
            self.client.get("/de/videos/video-html-ui/"),
        ):
            self.assertNotContains(response, "<script>alert")
            self.assertNotContains(response, "<b>Nicht")
            self.assertContains(
                response,
                "&lt;b&gt;Nicht vertrauenswürdiger Videotitel&lt;/b&gt;",
            )

    def test_image_loading_dimensions_alt_and_priority(self):
        self.client.force_login(self.subscriber)
        list_response = self.client.get(reverse("videos:list"))
        self.assertContains(
            list_response,
            f'src="{self.premium_video.miniature.url}" alt="MINIATURE-PREMIUM-SECRETE" width="1280" height="720" fetchpriority="high"',
        )
        self.assertContains(
            list_response,
            f'src="{self.public_video.miniature.url}" alt="Paysage public filmé" width="1280" height="720" loading="lazy"',
        )

        detail_response = self.client.get(
            reverse("videos:detail", args=[self.public_video.slug])
        )
        self.assertContains(
            detail_response,
            f'src="{self.public_video.miniature.url}" alt="Paysage public filmé" width="1280" height="720" fetchpriority="high"',
        )

    def test_iframe_has_restricted_accessible_attributes_and_no_autoplay(self):
        response = self.client.get(
            reverse("videos:detail", args=[self.public_video.slug])
        )
        parser = VideoDocumentParser()
        parser.feed(response.content.decode())
        self.assertEqual(len(parser.iframes), 1)
        iframe = parser.iframes[0]
        self.assertEqual(
            iframe["src"],
            f"https://www.youtube-nocookie.com/embed/{PUBLIC_YOUTUBE_ID}",
        )
        self.assertEqual(iframe["loading"], "lazy")
        self.assertEqual(
            iframe["referrerpolicy"],
            "strict-origin-when-cross-origin",
        )
        self.assertEqual(iframe["allow"], "encrypted-media; picture-in-picture")
        self.assertIn("allowfullscreen", iframe)
        self.assertTrue(iframe["title"].startswith("Lecteur vidéo :"))
        self.assertNotIn("autoplay", response.content.decode().lower())

    def test_public_routes_and_unknown_video_status_are_preserved(self):
        self.assertEqual(self.client.get(reverse("videos:list")).status_code, 200)
        self.assertEqual(
            self.client.get(
                reverse("videos:detail", args=[self.public_video.slug])
            ).status_code,
            200,
        )
        self.assertEqual(self.client.get("/videos/inconnue-ui/").status_code, 404)


class VideoPremiumUIListStateTests(TestCase):
    def setUp(self):
        translation.activate("fr")
        self.addCleanup(translation.activate, "fr")

    @staticmethod
    def _video(index, **kwargs):
        values = {
            "titre": f"Vidéo pagination {index}",
            "description": f"Description pagination {index}",
            "youtube_url": f"https://youtu.be/{PUBLIC_YOUTUBE_ID}",
            "slug": f"video-pagination-ui-{index}",
            "est_publie": True,
        }
        values.update(kwargs)
        return Video.objects.create(**values)

    def test_empty_list_uses_shared_empty_state(self):
        response = self.client.get(reverse("videos:list"))
        self.assertContains(response, 'class="empty-state videos-empty"')
        self.assertContains(response, "Aucune vidéo pour le moment")

    def test_single_video_has_no_empty_state(self):
        self._video(1)
        response = self.client.get(reverse("videos:list"))
        self.assertContains(response, "Vidéo pagination 1")
        self.assertNotContains(response, "Aucune vidéo pour le moment")

    def test_existing_pagination_parameter_is_preserved(self):
        for index in range(7):
            self._video(index)
        first_page = self.client.get(reverse("videos:list"))
        second_page = self.client.get(reverse("videos:list"), {"page": 2})
        self.assertTrue(first_page.context["page_obj"].has_next())
        self.assertContains(first_page, "?page=2")
        self.assertEqual(second_page.context["page_obj"].number, 2)
        self.assertContains(second_page, "?page=1")


class VideoPremiumUIStaticTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base_dir = Path(settings.BASE_DIR)
        cls.css = (base_dir / "static" / "css" / "videos.css").read_text(
            encoding="utf-8"
        )
        cls.styles_css = (base_dir / "static" / "css" / "styles.css").read_text(
            encoding="utf-8"
        )
        cls.card_template = (
            base_dir / "videos" / "templates" / "videos" / "_video_card.html"
        ).read_text(encoding="utf-8")
        cls.detail_template = (
            base_dir / "videos" / "templates" / "videos" / "detail.html"
        ).read_text(encoding="utf-8")

    def test_video_styles_only_use_foundation_colors(self):
        self.assertNotIn("!important", self.css)
        self.assertIsNone(re.search(r"#[0-9a-f]{3,8}\b", self.css, re.I))
        self.assertIsNone(re.search(r"\brgba?\(", self.css, re.I))

    def test_video_styles_use_no_undefined_application_variables(self):
        all_css = self.styles_css + "\n" + self.css
        used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", all_css, re.I))
        defined = set(
            re.findall(r"(--[a-z0-9-]+)\s*:\s*[^;{}]+;", all_css, re.I)
        )
        self.assertEqual(used - defined, set())

    def test_static_cards_have_no_hover_animation(self):
        self.assertNotIn(".video-card:hover", self.css)
        card_rule = re.search(r"\.video-card\s*\{([^}]*)\}", self.css).group(1)
        self.assertNotIn("transition", card_rule)
        self.assertNotIn("transform", card_rule)
        self.assertIn(".video-card-media:hover img", self.css)

    def test_responsive_focus_and_reduced_motion_guards_are_present(self):
        for marker in (
            "@media (max-width: 1099.98px)",
            "@media (max-width: 991.98px)",
            "@media (max-width: 767.98px)",
            "@media (max-width: 419.98px)",
            "@media (prefers-reduced-motion: reduce)",
            ":focus-visible",
            "aspect-ratio: 16 / 9",
            "aspect-ratio: 9 / 16",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.css)
        self.assertNotIn("overflow-x: hidden", self.css)

    def test_templates_reuse_shared_components_and_keep_escaping(self):
        self.assertIn("surface-card video-card", self.card_template)
        self.assertIn("badge badge-warning", self.card_template)
        self.assertIn("surface-card video-description", self.detail_template)
        self.assertNotRegex(self.card_template, r"\|safe\b")
        self.assertNotRegex(self.detail_template, r"\|safe\b")
        self.assertEqual(self.detail_template.count("<h1"), 1)
        self.assertNotIn("autoplay", self.detail_template.lower())

