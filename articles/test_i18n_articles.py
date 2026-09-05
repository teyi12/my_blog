from datetime import timedelta

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone, translation
from modeltranslation.admin import TranslationAdmin

from monetization.models import Abonnement, AbonnementUtilisateur

from .admin import ArticleAdmin
from .forms import ArticleForm
from .models import Article


class ArticleEditorialI18nTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = get_user_model().objects.create_user(
            email="author-i18n@example.com",
            password="test-password",
        )
        cls.staff = get_user_model().objects.create_user(
            email="staff-i18n@example.com",
            password="test-password",
            is_staff=True,
        )
        cls.article = Article.objects.create(
            titre="Titre français",
            titre_fr="Titre français",
            titre_de="Deutscher Titel",
            titre_en="English title",
            contenu="<strong>Contenu français</strong>",
            contenu_fr="<strong>Contenu français</strong>",
            contenu_de="<strong>Deutscher Inhalt</strong>",
            contenu_en="<strong>English content</strong>",
            slug="titre-francais",
            image="articles/cloudinary-original.jpg",
            auteur=cls.author,
        )
        cls.fallback_article = Article.objects.create(
            titre="Titre français de secours",
            contenu="Contenu français de secours",
            slug="titre-francais-secours",
            auteur=cls.author,
        )

    def test_list_and_detail_display_french_content(self):
        list_response = self.client.get("/articles/")
        detail_response = self.client.get("/articles/titre-francais/")

        self.assertContains(list_response, "Titre français")
        self.assertContains(list_response, "Contenu français")
        self.assertContains(detail_response, "Titre français")
        self.assertContains(detail_response, "Contenu français")

    def test_list_and_detail_display_german_translations(self):
        list_response = self.client.get("/de/articles/")
        detail_response = self.client.get("/de/articles/titre-francais/")

        self.assertContains(list_response, "Deutscher Titel")
        self.assertContains(list_response, "Deutscher Inhalt")
        self.assertContains(list_response, "Lesestoff für neue Perspektiven.")
        self.assertContains(detail_response, "Deutscher Titel")
        self.assertContains(detail_response, "Deutscher Inhalt")
        self.assertContains(detail_response, "Alle Artikel")

    def test_list_and_detail_display_english_translations(self):
        list_response = self.client.get("/en/articles/")
        detail_response = self.client.get("/en/articles/titre-francais/")

        self.assertContains(list_response, "English title")
        self.assertContains(list_response, "English content")
        self.assertContains(list_response, "Reading for a broader perspective.")
        self.assertContains(detail_response, "English title")
        self.assertContains(detail_response, "English content")
        self.assertContains(detail_response, "All articles")

    def test_german_and_english_fall_back_to_french(self):
        for prefix in ("de", "en"):
            with self.subTest(language=prefix):
                response = self.client.get(
                    f"/{prefix}/articles/titre-francais-secours/"
                )
                self.assertContains(response, "Titre français de secours")
                self.assertContains(response, "Contenu français de secours")

    def test_one_stable_slug_resolves_in_every_language(self):
        expected_urls = {
            "fr": "/articles/titre-francais/",
            "de": "/de/articles/titre-francais/",
            "en": "/en/articles/titre-francais/",
        }
        for language, expected_url in expected_urls.items():
            with self.subTest(language=language), translation.override(language):
                self.assertEqual(
                    reverse("articles:article_detail", args=[self.article.slug]),
                    expected_url,
                )
                self.assertEqual(self.client.get(expected_url).status_code, 200)
        self.assertEqual(self.article.slug, "titre-francais")

    def test_image_url_is_unchanged_and_alt_is_translated(self):
        expected_titles = {
            "fr": "Titre français",
            "de": "Deutscher Titel",
            "en": "English title",
        }
        image_url = self.article.image.url
        for language, title in expected_titles.items():
            prefix = "" if language == "fr" else f"/{language}"
            with self.subTest(language=language):
                response = self.client.get(
                    f"{prefix}/articles/titre-francais/"
                )
                self.assertContains(response, f'src="{image_url}" alt="{title}"')
                self.assertNotContains(response, f'src="{image_url}" alt=""')
                self.article.refresh_from_db()
                self.assertEqual(
                    self.article.image.name,
                    "articles/cloudinary-original.jpg",
                )

    def test_article_admin_is_multilingual_and_slug_is_stable_on_change(self):
        registered_admin = admin.site._registry[Article]
        self.assertIsInstance(registered_admin, TranslationAdmin)
        self.assertIsInstance(registered_admin, ArticleAdmin)
        self.assertEqual(registered_admin.prepopulated_fields, {"slug": ("titre_fr",)})
        self.assertEqual(
            registered_admin.search_fields,
            (
                "titre_fr",
                "titre_de",
                "titre_en",
                "contenu_fr",
                "contenu_de",
                "contenu_en",
                "auteur__email",
            ),
        )
        request = RequestFactory().get("/admin/articles/article/")
        request.user = self.staff
        self.assertNotIn("slug", registered_admin.get_readonly_fields(request))
        self.assertIn(
            "slug",
            registered_admin.get_readonly_fields(request, self.article),
        )
        self.assertEqual(
            registered_admin.get_prepopulated_fields(request),
            {"slug": ("titre_fr",)},
        )
        self.assertEqual(
            registered_admin.get_prepopulated_fields(request, self.article),
            {},
        )
        form = registered_admin.get_form(request)()
        for field_name in (
            "titre_fr",
            "titre_de",
            "titre_en",
            "contenu_fr",
            "contenu_de",
            "contenu_en",
        ):
            self.assertIn(field_name, form.fields)
        self.assertEqual(str(form.fields["titre_fr"].label), "Titre [fr]")
        self.assertEqual(str(form.fields["titre_de"].label), "Titre [de]")
        self.assertEqual(str(form.fields["titre_en"].label), "Titre [en]")
        self.assertEqual(str(form.fields["contenu_fr"].label), "Contenu [fr]")
        self.assertEqual(str(form.fields["contenu_de"].label), "Contenu [de]")
        self.assertEqual(str(form.fields["contenu_en"].label), "Contenu [en]")
        results, use_distinct = registered_admin.get_search_results(
            request,
            Article.objects.all(),
            "Deutscher Titel",
        )
        self.assertIn(self.article, results)
        self.assertFalse(use_distinct)

    def test_public_editor_has_explicit_translation_fields(self):
        with translation.override("fr"):
            form = ArticleForm()
        self.assertNotIn("titre", form.fields)
        self.assertNotIn("contenu", form.fields)
        self.assertNotIn("slug", form.fields)
        self.assertNotIn("auteur", form.fields)
        self.assertTrue(form.fields["titre_fr"].required)
        self.assertTrue(form.fields["contenu_fr"].required)
        for field_name in ("titre_de", "titre_en", "contenu_de", "contenu_en"):
            self.assertFalse(form.fields[field_name].required)
        with translation.override("fr"):
            self.assertEqual(str(form.fields["titre_fr"].label), "Titre [fr]")
            self.assertEqual(str(form.fields["contenu_en"].label), "Contenu [en]")
        with translation.override("de"):
            self.assertEqual(
                str(ArticleForm().fields["titre_fr"].label),
                "Titel [fr]",
            )
        with translation.override("en"):
            self.assertEqual(
                str(ArticleForm().fields["contenu_de"].label),
                "Content [de]",
            )

    def test_public_editor_generates_slug_from_french_title_and_keeps_it(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            "/de/articles/creer/",
            {
                "titre_fr": "Titre créé en français",
                "titre_de": "Auf Deutsch bearbeitet",
                "titre_en": "",
                "contenu_fr": "Corps français",
                "contenu_de": "Deutscher Text",
                "contenu_en": "",
                "sponsor": "",
            },
        )
        self.assertRedirects(response, "/de/articles/")
        article = Article.objects.get(titre_fr="Titre créé en français")
        self.assertEqual(article.slug, "titre-cree-en-francais")
        self.assertEqual(article.auteur, self.staff)

        response = self.client.post(
            f"/de/articles/{article.slug}/modifier/",
            {
                "titre_fr": "Nouveau titre français",
                "titre_de": "Neuer deutscher Titel",
                "titre_en": "",
                "contenu_fr": "Corps français modifié",
                "contenu_de": "Deutscher Text geändert",
                "contenu_en": "",
                "sponsor": "",
            },
        )
        self.assertRedirects(response, "/de/articles/")
        article.refresh_from_db()
        self.assertEqual(article.slug, "titre-cree-en-francais")
        self.assertEqual(article.auteur, self.staff)

    def test_non_staff_author_cannot_use_editor_views(self):
        self.client.force_login(self.author)
        for path in (
            "/articles/creer/",
            f"/articles/{self.article.slug}/modifier/",
            f"/articles/{self.article.slug}/supprimer/",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/admin/login/", response["Location"])


class ArticlePremiumI18nRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.free_user = User.objects.create_user(
            email="free-i18n@example.com", password="test-password"
        )
        cls.subscriber = User.objects.create_user(
            email="subscriber-i18n@example.com", password="test-password"
        )
        cls.expired_user = User.objects.create_user(
            email="expired-i18n@example.com", password="test-password"
        )
        cls.staff = User.objects.create_user(
            email="staff-premium-i18n@example.com",
            password="test-password",
            is_staff=True,
        )
        cls.superuser = User.objects.create_superuser(
            email="super-i18n@example.com", password="test-password"
        )
        plan = Abonnement.objects.create(
            nom="Premium i18n",
            prix="9.99",
            duree_jours=30,
            description="Accès premium",
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
            date_fin=now,
            actif=True,
        )
        cls.public_article = Article.objects.create(
            titre="Article public i18n",
            contenu="Contenu public i18n",
            slug="article-public-i18n",
        )
        cls.premium_article = Article.objects.create(
            titre="Article premium i18n",
            contenu="Contenu premium i18n",
            slug="article-premium-i18n",
            is_premium=True,
        )

    @staticmethod
    def _path(language, slug):
        prefix = "" if language == "fr" else f"/{language}"
        return f"{prefix}/articles/{slug}/"

    def test_public_article_is_accessible_in_all_languages(self):
        for language in ("fr", "de", "en"):
            with self.subTest(language=language):
                response = self.client.get(
                    self._path(language, self.public_article.slug)
                )
                self.assertEqual(response.status_code, 200)

    def test_anonymous_user_is_redirected_to_localized_login_with_next(self):
        for language in ("fr", "de", "en"):
            with self.subTest(language=language):
                path = self._path(language, self.premium_article.slug)
                prefix = "" if language == "fr" else f"/{language}"
                response = self.client.get(path)
                self.assertRedirects(
                    response,
                    f"{prefix}/accounts/login/?next={path}",
                )

    def test_free_and_strictly_expired_users_are_refused_in_all_languages(self):
        for user in (self.free_user, self.expired_user):
            self.client.force_login(user)
            for language in ("fr", "de", "en"):
                with self.subTest(user=user.email, language=language):
                    prefix = "" if language == "fr" else f"/{language}"
                    response = self.client.get(
                        self._path(language, self.premium_article.slug)
                    )
                    self.assertRedirects(
                        response,
                        f"{prefix}/monetization/abonnements/",
                    )
            self.client.logout()

    def test_subscriber_staff_and_superuser_are_allowed_in_all_languages(self):
        for user in (self.subscriber, self.staff, self.superuser):
            self.client.force_login(user)
            for language in ("fr", "de", "en"):
                with self.subTest(user=user.email, language=language):
                    response = self.client.get(
                        self._path(language, self.premium_article.slug)
                    )
                    self.assertEqual(response.status_code, 200)
            self.client.logout()
