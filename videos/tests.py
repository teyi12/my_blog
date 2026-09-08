from datetime import timedelta

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.text import slugify
from modeltranslation.admin import TranslationAdmin
from modeltranslation.translator import translator

from articles.models import CategorieArticle
from monetization.models import Abonnement, AbonnementUtilisateur

from .admin import VideoAdmin
from .models import Video


YOUTUBE_ID = "dQw4w9WgXcQ"


def create_video(title, **kwargs):
    defaults = {
        "titre": title,
        "description": f"Description de {title}",
        "youtube_url": f"https://www.youtube.com/watch?v={YOUTUBE_ID}",
        "est_publie": True,
    }
    defaults.update(kwargs)
    return Video.objects.create(**defaults)


class VideoModelAndYouTubeValidationTests(TestCase):
    def test_only_expected_fields_are_translated(self):
        options = translator.get_options_for_model(Video)

        self.assertEqual(
            set(options.fields),
            {"titre", "description", "miniature_alt"},
        )
        self.assertEqual(options.required_languages, {"fr": ("titre", "description")})
        for field_name in (
            "titre_fr",
            "titre_de",
            "titre_en",
            "description_fr",
            "description_de",
            "description_en",
            "miniature_alt_fr",
            "miniature_alt_de",
            "miniature_alt_en",
        ):
            self.assertIsNotNone(Video._meta.get_field(field_name))
        for field_name in (
            "slug_fr",
            "youtube_url_fr",
            "miniature_fr",
            "categorie_fr",
            "est_publie_fr",
        ):
            with self.assertRaises(FieldDoesNotExist):
                Video._meta.get_field(field_name)

    def test_supported_youtube_urls_produce_safe_id_and_embed_url(self):
        urls = (
            f"https://youtube.com/watch?v={YOUTUBE_ID}",
            f"https://www.youtube.com/watch?v={YOUTUBE_ID}&feature=share",
            f"https://youtu.be/{YOUTUBE_ID}",
            f"https://youtube.com/shorts/{YOUTUBE_ID}",
        )

        for index, url in enumerate(urls):
            with self.subTest(url=url):
                video = Video(
                    titre=f"Vidéo {index}",
                    description="Description",
                    youtube_url=url,
                )
                video.full_clean()
                video.save()
                self.assertEqual(video.youtube_id, YOUTUBE_ID)
                self.assertEqual(
                    video.embed_url,
                    f"https://www.youtube-nocookie.com/embed/{YOUTUBE_ID}",
                )

    def test_invalid_youtube_values_are_rejected_on_save(self):
        invalid_values = (
            f"http://youtube.com/watch?v={YOUTUBE_ID}",
            f"https://example.com/watch?v={YOUTUBE_ID}",
            f"https://youtube.com.evil.test/watch?v={YOUTUBE_ID}",
            f"https://youtube.com/embed/{YOUTUBE_ID}",
            "javascript:alert(1)",
            "data:text/html,test",
            f'<iframe src="https://youtube.com/watch?v={YOUTUBE_ID}"></iframe>',
            "https://youtu.be/invalid-id",
            "https://youtube.com/watch?v=",
        )

        for index, url in enumerate(invalid_values):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                Video.objects.create(
                    titre=f"Valeur invalide {index}",
                    description="Description",
                    youtube_url=url,
                )

    def test_slug_is_generated_from_french_and_is_shared_by_all_languages(self):
        with translation.override("de"):
            video = Video.objects.create(
                titre_fr="Carnet Vidéo Français",
                titre_de="Deutsches Videotagebuch",
                titre_en="English video journal",
                description_fr="Description française",
                youtube_url=f"https://youtu.be/{YOUTUBE_ID}",
            )

        self.assertEqual(video.slug, slugify(video.titre_fr))
        expected = {
            "fr": f"/videos/{video.slug}/",
            "de": f"/de/videos/{video.slug}/",
            "en": f"/en/videos/{video.slug}/",
        }
        for language, url in expected.items():
            with self.subTest(language=language), translation.override(language):
                self.assertEqual(reverse("videos:detail", args=[video.slug]), url)


class VideoPublicPagesAndI18nTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = CategorieArticle.objects.create(
            nom="Voyages",
            nom_fr="Voyages",
            nom_de="Reisen",
            nom_en="Travel",
            slug="voyages-video",
        )
        cls.video = create_video(
            "Journal français",
            titre_fr="Journal français",
            titre_de="Deutsches Tagebuch",
            titre_en="English journal",
            description_fr="Description française de la vidéo.",
            description_de="Deutsche Videobeschreibung.",
            description_en="English video description.",
            miniature="videos/thumbnails/journal.jpg",
            miniature_alt_fr="Paysage français",
            miniature_alt_de="Deutsche Landschaft",
            miniature_alt_en="English landscape",
            categorie=cls.category,
        )
        cls.fallback_video = create_video(
            "Contenu français de secours",
            description="Description française de secours.",
            slug="contenu-francais-secours",
        )
        cls.french_alt_fallback = create_video(
            "Titre français avec alternative",
            titre_de="Deutscher Titel mit Alternative",
            titre_en="English title with alt",
            description="Description",
            slug="alternative-francaise",
            miniature="videos/thumbnails/fallback.jpg",
            miniature_alt="Alternative française",
        )
        cls.title_alt_fallback = create_video(
            "Titre français",
            titre_de="Deutscher Ersatztitel",
            titre_en="English fallback title",
            description="Description",
            slug="alternative-titre",
        )

    def test_list_and_detail_use_active_dynamic_translations(self):
        expected = {
            "fr": ("", "Journal français", "Description française", "Voyages"),
            "de": ("/de", "Deutsches Tagebuch", "Deutsche Videobeschreibung", "Reisen"),
            "en": ("/en", "English journal", "English video description", "Travel"),
        }
        for language, (prefix, title, description, category) in expected.items():
            with self.subTest(language=language):
                list_response = self.client.get(f"{prefix}/videos/")
                detail_response = self.client.get(
                    f"{prefix}/videos/{self.video.slug}/"
                )
                self.assertContains(list_response, title)
                self.assertContains(list_response, category)
                self.assertContains(detail_response, title)
                self.assertContains(detail_response, description)
                self.assertContains(detail_response, category)

    def test_static_video_content_is_translated_in_german_and_english(self):
        expected = {
            "de": (
                "Geschichten, die man in Bildern erleben kann.",
                "Video ansehen",
                "Alle Videos",
                "Über dieses Video",
            ),
            "en": (
                "Stories to experience through images.",
                "Watch video",
                "All videos",
                "About this video",
            ),
        }
        for language, strings in expected.items():
            with self.subTest(language=language):
                list_response = self.client.get(f"/{language}/videos/")
                detail_response = self.client.get(
                    f"/{language}/videos/{self.video.slug}/"
                )
                for value in strings[:2]:
                    self.assertContains(list_response, value)
                for value in strings[2:]:
                    self.assertContains(detail_response, value)

    def test_french_is_unprefixed_and_literal_fr_route_is_absent(self):
        self.assertEqual(self.client.get("/videos/").status_code, 200)
        self.assertEqual(self.client.get("/fr/videos/").status_code, 404)

    def test_missing_german_and_english_content_falls_back_to_french(self):
        for language in ("de", "en"):
            with self.subTest(language=language):
                response = self.client.get(f"/{language}/videos/")
                self.assertContains(response, "Contenu français de secours")
                self.assertContains(response, "Description française de secours.")

    def test_thumbnail_alt_uses_translation_then_french_then_translated_title(self):
        expectations = {
            "fr": "Paysage français",
            "de": "Deutsche Landschaft",
            "en": "English landscape",
        }
        for language, alt in expectations.items():
            with self.subTest(translated=language), translation.override(language):
                self.video.refresh_from_db()
                self.assertEqual(self.video.resolved_miniature_alt, alt)

        for language in ("de", "en"):
            with self.subTest(french_fallback=language), translation.override(language):
                self.french_alt_fallback.refresh_from_db()
                self.assertEqual(
                    self.french_alt_fallback.resolved_miniature_alt,
                    "Alternative française",
                )

        for language, title in {
            "fr": "Titre français",
            "de": "Deutscher Ersatztitel",
            "en": "English fallback title",
        }.items():
            with self.subTest(title_fallback=language), translation.override(language):
                self.title_alt_fallback.refresh_from_db()
                self.assertEqual(self.title_alt_fallback.resolved_miniature_alt, title)

    def test_missing_thumbnail_uses_versioned_static_placeholder_and_non_empty_alt(self):
        response = self.client.get(f"/videos/{self.title_alt_fallback.slug}/")

        self.assertContains(response, 'src="/static/images/video-placeholder.svg"')
        self.assertContains(response, 'alt="Titre français"')
        self.assertNotContains(
            response,
            'src="/static/images/video-placeholder.svg" alt=""',
        )

    def test_detail_renders_responsive_private_player_without_autoplay(self):
        response = self.client.get(f"/videos/{self.video.slug}/")

        self.assertContains(response, 'class="video-player"')
        self.assertContains(
            response,
            f'src="https://www.youtube-nocookie.com/embed/{YOUTUBE_ID}"',
        )
        self.assertContains(response, 'loading="lazy"')
        self.assertContains(response, 'referrerpolicy="strict-origin-when-cross-origin"')
        self.assertContains(response, "allowfullscreen")
        self.assertNotContains(response, "autoplay")
        self.assertNotContains(response, "youtube.com/iframe_api")

    def test_navigation_is_localized_and_keeps_expected_urls(self):
        expected = {
            "fr": ("/videos/", "Vidéos"),
            "de": ("/de/videos/", "Videos"),
            "en": ("/en/videos/", "Videos"),
        }
        for language, (url, label) in expected.items():
            with self.subTest(language=language):
                response = self.client.get(url)
                self.assertContains(response, f'href="{url}">{label}</a>', count=2)


class VideoListOrganizationTests(TestCase):
    def test_list_contains_only_published_videos_and_draft_detail_is_404(self):
        published = create_video("Vidéo publiée", slug="video-publiee")
        draft = create_video(
            "Brouillon vidéo",
            slug="brouillon-video",
            est_publie=False,
        )

        response = self.client.get("/videos/")

        self.assertContains(response, published.titre)
        self.assertNotContains(response, draft.titre)
        self.assertEqual(
            self.client.get(f"/videos/{draft.slug}/").status_code,
            404,
        )

    def test_featured_video_is_large_and_not_duplicated(self):
        featured = create_video(
            "Vidéo à la une",
            slug="video-a-la-une",
            en_vedette=True,
        )
        create_video("Autre vidéo", slug="autre-video")

        response = self.client.get("/videos/")

        self.assertContains(response, 'class="videos-featured"')
        self.assertContains(response, f'data-video-id="{featured.pk}"', count=1)

    def test_multiple_featured_rows_created_externally_have_deterministic_display(self):
        first = create_video("Première vidéo", slug="premiere-video", ordre_affichage=1)
        second = create_video("Seconde vidéo", slug="seconde-video", ordre_affichage=2)
        Video.objects.filter(pk__in=(first.pk, second.pk)).update(en_vedette=True)

        response = self.client.get("/videos/")

        self.assertEqual(response.context["featured_video"].pk, first.pk)
        self.assertContains(response, f'data-video-id="{first.pk}"', count=1)
        self.assertContains(response, f'data-video-id="{second.pk}"', count=1)

    def test_order_is_manual_then_newest_then_highest_identifier(self):
        older = create_video("Ordre deux ancien", slug="ordre-deux-ancien", ordre_affichage=2)
        newer = create_video("Ordre deux récent", slug="ordre-deux-recent", ordre_affichage=2)
        no_order = create_video("Sans ordre", slug="sans-ordre")
        earlier = timezone.now() - timedelta(days=2)
        Video.objects.filter(pk=older.pk).update(date_publication=earlier)

        response = self.client.get("/videos/")
        ids = [video.pk for video in response.context["page_obj"].object_list]

        self.assertLess(ids.index(newer.pk), ids.index(older.pk))
        self.assertLess(ids.index(older.pk), ids.index(no_order.pk))


class VideoPremiumAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.plan = Abonnement.objects.create(
            nom="Premium vidéo",
            prix="9.99",
            duree_jours=30,
            description="Accès Premium",
        )
        cls.public_video = create_video(
            "Vidéo publique",
            slug="video-publique",
            is_premium=False,
        )
        cls.premium_video = create_video(
            "Vidéo Premium",
            slug="video-premium",
            is_premium=True,
        )
        cls.free_user = get_user_model().objects.create_user(
            email="video-free@example.com", password="test-password"
        )
        cls.active_user = get_user_model().objects.create_user(
            email="video-active@example.com", password="test-password"
        )
        cls.inactive_user = get_user_model().objects.create_user(
            email="video-inactive@example.com", password="test-password"
        )
        cls.expired_user = get_user_model().objects.create_user(
            email="video-expired@example.com", password="test-password"
        )
        cls.future_user = get_user_model().objects.create_user(
            email="video-future@example.com", password="test-password"
        )
        cls.staff = get_user_model().objects.create_user(
            email="video-staff@example.com",
            password="test-password",
            is_staff=True,
        )
        cls.superuser = get_user_model().objects.create_superuser(
            email="video-superuser@example.com", password="test-password"
        )
        now = timezone.now()
        AbonnementUtilisateur.objects.create(
            utilisateur=cls.active_user,
            abonnement=cls.plan,
            date_fin=now + timedelta(days=30),
            actif=True,
        )
        AbonnementUtilisateur.objects.create(
            utilisateur=cls.inactive_user,
            abonnement=cls.plan,
            date_fin=now + timedelta(days=30),
            actif=False,
        )
        AbonnementUtilisateur.objects.create(
            utilisateur=cls.expired_user,
            abonnement=cls.plan,
            date_fin=now - timedelta(seconds=1),
            actif=True,
        )
        future_subscription = AbonnementUtilisateur.objects.create(
            utilisateur=cls.future_user,
            abonnement=cls.plan,
            date_fin=now + timedelta(days=30),
            actif=True,
        )
        AbonnementUtilisateur.objects.filter(pk=future_subscription.pk).update(
            date_debut=now + timedelta(days=1)
        )

    def test_public_video_is_available_anonymously(self):
        response = self.client.get(f"/videos/{self.public_video.slug}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.public_video.titre)

    def test_anonymous_premium_access_redirects_to_login_with_next(self):
        url = f"/videos/{self.premium_video.slug}/"

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_free_inactive_future_and_expired_users_are_refused(self):
        for user in (
            self.free_user,
            self.inactive_user,
            self.future_user,
            self.expired_user,
        ):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(f"/videos/{self.premium_video.slug}/")
                self.assertRedirects(response, reverse("monetization:abonnements"))
                self.client.logout()

    def test_active_staff_and_superuser_can_access_premium_video(self):
        for user in (self.active_user, self.staff, self.superuser):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(f"/videos/{self.premium_video.slug}/")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.premium_video.titre)
                self.client.logout()


class VideoAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_superuser(
            email="video-admin@example.com", password="test-password"
        )

    def _request(self):
        request = RequestFactory().get("/admin/videos/video/")
        request.user = self.staff
        return request

    def test_admin_is_translation_admin_with_required_french_content(self):
        video_admin = admin.site._registry[Video]
        form = video_admin.get_form(self._request())()

        self.assertIsInstance(video_admin, TranslationAdmin)
        self.assertIsInstance(video_admin, VideoAdmin)
        for field_name in (
            "titre_fr",
            "titre_de",
            "titre_en",
            "description_fr",
            "description_de",
            "description_en",
            "miniature_alt_fr",
            "miniature_alt_de",
            "miniature_alt_en",
        ):
            self.assertIn(field_name, form.fields)
        self.assertTrue(form.fields["titre_fr"].required)
        self.assertTrue(form.fields["description_fr"].required)
        for field_name in (
            "titre_de",
            "titre_en",
            "description_de",
            "description_en",
            "miniature_alt_fr",
            "miniature_alt_de",
            "miniature_alt_en",
        ):
            self.assertFalse(form.fields[field_name].required)
        self.assertEqual(video_admin.prepopulated_fields, {"slug": ("titre_fr",)})
        self.assertEqual(
            video_admin.search_fields,
            ("titre_fr", "titre_de", "titre_en", "auteur__email"),
        )

    def test_admin_assigns_author_and_replaces_previous_featured_video(self):
        previous = create_video(
            "Ancienne vidéo à la une",
            slug="ancienne-video-une",
            en_vedette=True,
        )
        video = Video(
            titre="Nouvelle vidéo à la une",
            description="Description",
            youtube_url=f"https://youtu.be/{YOUTUBE_ID}",
            en_vedette=True,
        )

        admin.site._registry[Video].save_model(
            self._request(), video, form=None, change=False
        )

        previous.refresh_from_db()
        self.assertEqual(video.auteur, self.staff)
        self.assertFalse(previous.en_vedette)
        self.assertTrue(video.en_vedette)
        self.assertEqual(Video.objects.filter(en_vedette=True).count(), 1)
