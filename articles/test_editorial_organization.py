from datetime import timedelta

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone, translation
from django.utils.text import slugify
from modeltranslation.admin import TranslationAdmin

from shop.models import Categorie as CategorieProduit

from .admin import ArticleAdmin, ArticleMediaInline, CategorieArticleAdmin
from .forms import ArticleForm
from .models import Article, CategorieArticle


class ArticleCategoryAndAltTextTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = get_user_model().objects.create_user(
            email="editorial-category@example.com",
            password="test-password",
        )
        cls.category = CategorieArticle.objects.create(
            nom="Voyages",
            nom_fr="Voyages",
            nom_de="Reisen",
            nom_en="Travel",
            slug="voyages",
        )
        cls.fallback_category = CategorieArticle.objects.create(
            nom="Culture française",
            slug="culture-francaise",
        )
        cls.article = Article.objects.create(
            titre="Carnet français",
            titre_fr="Carnet français",
            titre_de="Deutsches Reisetagebuch",
            titre_en="English travel journal",
            contenu="Contenu français",
            slug="carnet-multilingue",
            image="articles/cloudinary-editorial.jpg",
            image_alt="Paysage français",
            image_alt_fr="Paysage français",
            image_alt_de="Deutsche Landschaft",
            image_alt_en="English landscape",
            categorie=cls.category,
            auteur=cls.author,
        )
        cls.french_alt_fallback = Article.objects.create(
            titre="Article avec texte français",
            titre_de="Artikel mit französischem Alternativtext",
            titre_en="Article with French alt text",
            contenu="Contenu",
            slug="texte-alternatif-francais",
            image_alt="Alternative française",
            image_alt_fr="Alternative française",
            categorie=cls.fallback_category,
        )
        cls.title_fallback = Article.objects.create(
            titre="Titre français de remplacement",
            titre_de="Deutscher Ersatztitel",
            titre_en="English fallback title",
            contenu="Contenu",
            slug="titre-alternatif-de-remplacement",
        )

    def test_article_categories_are_distinct_from_product_categories(self):
        self.assertIsNot(CategorieArticle, CategorieProduit)
        self.assertNotEqual(
            CategorieArticle._meta.db_table,
            CategorieProduit._meta.db_table,
        )
        self.assertIs(
            Article._meta.get_field("categorie").remote_field.model,
            CategorieArticle,
        )

    def test_category_name_uses_active_translation_and_french_fallback(self):
        expected = {"fr": "Voyages", "de": "Reisen", "en": "Travel"}
        for language, name in expected.items():
            with self.subTest(language=language), translation.override(language):
                self.category.refresh_from_db()
                self.assertEqual(self.category.nom, name)

        for language in ("de", "en"):
            with self.subTest(fallback=language), translation.override(language):
                self.fallback_category.refresh_from_db()
                self.assertEqual(self.fallback_category.nom, "Culture française")

    def test_image_alt_fields_use_active_translation(self):
        expected = {
            "fr": "Paysage français",
            "de": "Deutsche Landschaft",
            "en": "English landscape",
        }
        for language, alt_text in expected.items():
            with self.subTest(language=language), translation.override(language):
                self.article.refresh_from_db()
                self.assertEqual(self.article.resolved_image_alt, alt_text)

    def test_image_alt_falls_back_to_french_then_to_translated_title(self):
        for language in ("de", "en"):
            with self.subTest(french_fallback=language), translation.override(language):
                self.french_alt_fallback.refresh_from_db()
                self.assertEqual(
                    self.french_alt_fallback.resolved_image_alt,
                    "Alternative française",
                )

        expected_titles = {
            "fr": "Titre français de remplacement",
            "de": "Deutscher Ersatztitel",
            "en": "English fallback title",
        }
        for language, title in expected_titles.items():
            with self.subTest(title_fallback=language), translation.override(language):
                self.title_fallback.refresh_from_db()
                self.assertEqual(self.title_fallback.resolved_image_alt, title)

    def test_list_and_detail_render_translated_category_and_alt_without_empty_alt(self):
        for language, prefix, category, alt_text in (
            ("fr", "", "Voyages", "Paysage français"),
            ("de", "/de", "Reisen", "Deutsche Landschaft"),
            ("en", "/en", "Travel", "English landscape"),
        ):
            with self.subTest(language=language):
                list_response = self.client.get(f"{prefix}/articles/")
                detail_response = self.client.get(
                    f"{prefix}/articles/{self.article.slug}/"
                )
                self.assertContains(list_response, category)
                self.assertContains(detail_response, category)
                self.assertContains(list_response, f'alt="{alt_text}"')
                self.assertContains(detail_response, f'alt="{alt_text}"')
                self.assertNotContains(
                    detail_response,
                    f'src="{self.article.image.url}" alt=""',
                )


class ArticleOrganizationAdminAndFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_superuser(
            email="editorial-admin@example.com",
            password="test-password",
        )
        cls.old_featured = Article.objects.create(
            titre="Ancienne une",
            contenu="Contenu",
            slug="ancienne-une",
            en_vedette=True,
        )

    def _request(self):
        request = RequestFactory().get("/admin/articles/article/")
        request.user = self.staff
        return request

    def test_category_admin_is_multilingual_with_required_french(self):
        category_admin = admin.site._registry[CategorieArticle]
        form = category_admin.get_form(self._request())()

        self.assertIsInstance(category_admin, TranslationAdmin)
        self.assertIsInstance(category_admin, CategorieArticleAdmin)
        self.assertTrue(form.fields["nom_fr"].required)
        self.assertFalse(form.fields["nom_de"].required)
        self.assertFalse(form.fields["nom_en"].required)
        self.assertEqual(category_admin.prepopulated_fields, {"slug": ("nom_fr",)})
        self.assertEqual(
            category_admin.search_fields,
            ("nom_fr", "nom_de", "nom_en"),
        )

    def test_article_admin_exposes_organization_and_alt_fields(self):
        article_admin = admin.site._registry[Article]
        form = article_admin.get_form(self._request())()

        self.assertIsInstance(article_admin, ArticleAdmin)
        for field_name in (
            "categorie",
            "image_alt_fr",
            "image_alt_de",
            "image_alt_en",
            "en_vedette",
            "ordre_affichage",
        ):
            self.assertIn(field_name, form.fields)
        for field_name in (
            "categorie",
            "en_vedette",
            "ordre_affichage",
            "is_premium",
            "date_publication",
        ):
            self.assertIn(field_name, article_admin.list_display)
        for field_name in ("categorie", "en_vedette", "is_premium"):
            self.assertIn(field_name, article_admin.list_filter)
        self.assertIn(ArticleMediaInline, article_admin.inlines)

    def test_admin_save_replaces_the_previous_featured_article(self):
        article_admin = admin.site._registry[Article]
        new_featured = Article(
            titre="Nouvelle une",
            contenu="Nouveau contenu",
            slug="nouvelle-une",
            en_vedette=True,
        )

        article_admin.save_model(self._request(), new_featured, form=None, change=False)

        self.old_featured.refresh_from_db()
        self.assertFalse(self.old_featured.en_vedette)
        self.assertTrue(new_featured.en_vedette)
        self.assertEqual(Article.objects.filter(en_vedette=True).count(), 1)

    def test_public_editor_keeps_technical_fields_protected(self):
        form = ArticleForm()

        for field_name in (
            "categorie",
            "image_alt_fr",
            "image_alt_de",
            "image_alt_en",
            "en_vedette",
            "ordre_affichage",
        ):
            self.assertIn(field_name, form.fields)
        self.assertNotIn("auteur", form.fields)
        self.assertNotIn("slug", form.fields)

    def test_public_editor_saves_category_alt_featured_and_order_for_staff(self):
        category = CategorieArticle.objects.create(
            nom="Innovation",
            slug="innovation",
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            "/articles/creer/",
            {
                "titre_fr": "Article éditorial organisé",
                "titre_de": "Organisierter Artikel",
                "titre_en": "Organized article",
                "contenu_fr": "Contenu français",
                "contenu_de": "Deutscher Inhalt",
                "contenu_en": "English content",
                "image_alt_fr": "Alternative française",
                "image_alt_de": "Deutscher Alternativtext",
                "image_alt_en": "English alternative text",
                "categorie": category.pk,
                "sponsor": "",
                "en_vedette": "on",
                "ordre_affichage": 4,
            },
        )

        self.assertRedirects(response, "/articles/")
        article = Article.objects.get(titre_fr="Article éditorial organisé")
        self.assertEqual(article.auteur, self.staff)
        self.assertEqual(article.slug, "article-editorial-organise")
        self.assertEqual(article.categorie, category)
        self.assertEqual(article.image_alt_fr, "Alternative française")
        self.assertEqual(article.image_alt_de, "Deutscher Alternativtext")
        self.assertEqual(article.image_alt_en, "English alternative text")
        self.assertTrue(article.en_vedette)
        self.assertEqual(article.ordre_affichage, 4)
        self.old_featured.refresh_from_db()
        self.assertFalse(self.old_featured.en_vedette)

    def test_new_form_labels_are_translated_in_german_and_english(self):
        with translation.override("de"):
            german_form = ArticleForm()
            self.assertEqual(
                str(german_form.fields["image_alt_fr"].label),
                "Alternativtext [fr]",
            )
            self.assertEqual(
                str(german_form.fields["ordre_affichage"].label),
                "Anzeigereihenfolge",
            )

        with translation.override("en"):
            english_form = ArticleForm()
            self.assertEqual(
                str(english_form.fields["image_alt_en"].label),
                "Alternative text [en]",
            )
            self.assertEqual(
                str(english_form.fields["en_vedette"].label),
                "Featured article",
            )


class ArticleOrganizationListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = get_user_model().objects.create_user(
            email="editorial-list@example.com",
            password="test-password",
        )

    @classmethod
    def _article(cls, title, **kwargs):
        slug = slugify(title)
        return Article.objects.create(
            titre=title,
            contenu=f"Contenu de {title}",
            slug=slug,
            auteur=cls.author,
            **kwargs,
        )

    def test_featured_article_has_one_responsive_large_block_and_no_duplicate(self):
        featured = self._article("Article vedette", en_vedette=True)
        regular = self._article("Article secondaire")

        response = self.client.get("/articles/")

        self.assertEqual(response.context["featured_article"], featured)
        self.assertNotIn(featured, response.context["page_obj"].object_list)
        self.assertIn(regular, response.context["page_obj"].object_list)
        self.assertContains(response, 'class="articles-featured"')
        self.assertContains(response, "article-card-featured")
        self.assertContains(response, 'class="img-fluid"')
        self.assertContains(response, f'data-article-id="{featured.pk}"', count=1)

    def test_multiple_external_featured_flags_are_resolved_deterministically(self):
        first = self._article("Première candidate", ordre_affichage=20)
        selected = self._article("Candidate retenue", ordre_affichage=10)
        Article.objects.filter(pk__in=(first.pk, selected.pk)).update(en_vedette=True)

        response = self.client.get("/articles/")

        self.assertEqual(response.context["featured_article"], selected)
        self.assertIn(first, response.context["page_obj"].object_list)
        self.assertNotIn(selected, response.context["page_obj"].object_list)
        self.assertContains(response, f'data-article-id="{first.pk}"', count=1)
        self.assertContains(response, f'data-article-id="{selected.pk}"', count=1)

    def test_manual_order_then_date_and_identifier_descending(self):
        now = timezone.now()
        ordered_old = self._article("Ordonné ancien", ordre_affichage=1)
        ordered_recent = self._article("Ordonné récent", ordre_affichage=1)
        ordered_recent_last = self._article("Ordonné récent dernier", ordre_affichage=1)
        second_priority = self._article("Deuxième priorité", ordre_affichage=2)
        unordered_old = self._article("Sans ordre ancien")
        unordered_recent = self._article("Sans ordre récent")
        Article.objects.filter(pk=ordered_old.pk).update(
            date_publication=now - timedelta(days=2)
        )
        Article.objects.filter(pk__in=(ordered_recent.pk, ordered_recent_last.pk)).update(
            date_publication=now - timedelta(days=1)
        )
        Article.objects.filter(pk=unordered_old.pk).update(
            date_publication=now - timedelta(days=3)
        )
        Article.objects.filter(pk=unordered_recent.pk).update(date_publication=now)

        response = self.client.get("/articles/")
        articles = list(response.context["page_obj"].object_list)

        self.assertEqual(
            articles,
            [
                ordered_recent_last,
                ordered_recent,
                ordered_old,
                second_priority,
                unordered_recent,
                unordered_old,
            ],
        )

    def test_without_featured_article_all_articles_use_the_regular_grid(self):
        first = self._article("Premier article")
        second = self._article("Second article")

        response = self.client.get("/articles/")

        self.assertIsNone(response.context["featured_article"])
        self.assertEqual(
            set(response.context["page_obj"].object_list),
            {first, second},
        )
        self.assertNotContains(response, "article-card-featured")

    def test_premium_article_can_be_featured_without_changing_detail_protection(self):
        premium = self._article(
            "Une premium",
            en_vedette=True,
            is_premium=True,
        )

        list_response = self.client.get("/articles/")
        detail_response = self.client.get(f"/articles/{premium.slug}/")

        self.assertEqual(list_response.context["featured_article"], premium)
        self.assertContains(list_response, "Premium")
        self.assertRedirects(
            detail_response,
            f"/accounts/login/?next=/articles/{premium.slug}/",
        )

    def test_featured_badge_is_translated_in_german_and_english(self):
        self._article("Une traduite", en_vedette=True)

        self.assertContains(self.client.get("/de/articles/"), "Hervorgehoben")
        self.assertContains(self.client.get("/en/articles/"), "Featured")
