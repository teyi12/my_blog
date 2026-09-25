import json
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from articles.models import Article, ArticleMedia, CategorieArticle
from monetization.models import Abonnement, AbonnementUtilisateur, Partenaire, Publicite
from shop.models import Categorie, Produit
from videos.models import Video


YOUTUBE_ID = "dQw4w9WgXcQ"


class PerformanceSeoSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.free_user = User.objects.create_user(
            email="audit-free@example.test",
            password="test-password",
        )
        cls.subscriber = User.objects.create_user(
            email="audit-subscriber@example.test",
            password="test-password",
        )
        cls.staff = User.objects.create_user(
            email="audit-staff@example.test",
            password="test-password",
            is_staff=True,
        )
        plan = Abonnement.objects.create(
            nom="Audit Premium",
            prix=Decimal("8.00"),
            duree_jours=30,
            description="Accès de test.",
        )
        AbonnementUtilisateur.objects.create(
            utilisateur=cls.subscriber,
            abonnement=plan,
            date_fin=timezone.now() + timedelta(days=30),
            actif=True,
        )
        cls.article_category = CategorieArticle.objects.create(
            nom="Audit éditorial",
            slug="audit-editorial",
        )
        cls.public_article = Article.objects.create(
            titre_fr="Article public audit",
            titre_de="Öffentlicher Audit-Artikel",
            titre_en="Public audit article",
            contenu_fr="Contenu public audit.",
            contenu_de="Öffentlicher Audit-Inhalt.",
            contenu_en="Public audit content.",
            slug="article-public-audit",
            image="articles/public-audit.jpg",
            categorie=cls.article_category,
        )
        cls.premium_article = Article.objects.create(
            titre="Dossier Premium audit",
            contenu="SECRET-ARTICLE-PREMIUM-AUDIT",
            slug="article-premium-audit",
            image="articles/secret-premium-audit.jpg",
            image_alt="SECRET-ALT-ARTICLE-AUDIT",
            is_premium=True,
            en_vedette=True,
            categorie=cls.article_category,
        )
        cls.premium_media = ArticleMedia.objects.create(
            article=cls.premium_article,
            type="image",
            fichier="medias/secret-premium-media-audit.jpg",
        )
        cls.public_video = Video.objects.create(
            titre="Vidéo publique audit",
            description="Description vidéo publique audit.",
            slug="video-publique-audit",
            youtube_url=f"https://www.youtube.com/watch?v={YOUTUBE_ID}",
            miniature="videos/thumbnails/public-audit.jpg",
            est_publie=True,
            categorie=cls.article_category,
        )
        cls.premium_video = Video.objects.create(
            titre="Vidéo Premium audit",
            description="SECRET-VIDEO-PREMIUM-AUDIT",
            slug="video-premium-audit",
            youtube_url=f"https://www.youtube.com/watch?v={YOUTUBE_ID}",
            miniature="videos/thumbnails/secret-premium-audit.jpg",
            miniature_alt="SECRET-ALT-VIDEO-AUDIT",
            est_publie=True,
            is_premium=True,
            en_vedette=True,
            categorie=cls.article_category,
        )
        cls.product_category = Categorie.objects.create(
            nom="Produits audit",
            slug="produits-audit",
        )
        cls.product = Produit.objects.create(
            nom_fr="Produit public audit",
            nom_de="Öffentliches Audit-Produkt",
            nom_en="Public audit product",
            description_fr="Description publique audit.",
            description_de="Öffentliche Audit-Beschreibung.",
            description_en="Public audit description.",
            slug="produit-public-audit",
            prix=Decimal("12.00"),
            image="produits/public-audit.jpg",
            categorie=cls.product_category,
            en_vedette=True,
        )

    @staticmethod
    def json_ld(response):
        match = re.search(
            r'<script id="structured-data" type="application/ld\+json">(.*?)</script>',
            response.content.decode(),
            re.S,
        )
        if not match:
            raise AssertionError("JSON-LD script not found")
        return json.loads(match.group(1))

    def test_home_never_exposes_locked_premium_content_or_media(self):
        for user in (None, self.free_user):
            with self.subTest(user=getattr(user, "email", "anonymous")):
                if user:
                    self.client.force_login(user)
                response = self.client.get(reverse("home"))
                self.assertContains(response, self.premium_article.titre)
                self.assertContains(response, self.premium_video.titre)
                for secret in (
                    self.premium_article.contenu,
                    self.premium_article.image.url,
                    self.premium_article.image_alt,
                    self.premium_video.description,
                    self.premium_video.miniature.url,
                    self.premium_video.miniature_alt,
                ):
                    self.assertNotContains(response, secret)
                self.client.logout()

        for user in (self.subscriber, self.staff):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(reverse("home"))
                self.assertContains(response, self.premium_article.contenu)
                self.assertContains(response, self.premium_article.image.url)
                self.assertContains(response, self.premium_video.description)
                self.assertContains(response, self.premium_video.miniature.url)
                self.client.logout()

    def test_premium_media_json_requires_existing_premium_access(self):
        url = reverse(
            "articles:article_media_json",
            args=[self.premium_article.slug],
        )
        for user in (None, self.free_user):
            with self.subTest(user=getattr(user, "email", "anonymous")):
                if user:
                    self.client.force_login(user)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)
                self.assertNotContains(
                    response,
                    self.premium_media.fichier.url,
                    status_code=403,
                )
                self.client.logout()

        for user in (self.subscriber, self.staff):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.premium_media.fichier.url)
                self.client.logout()

    def test_rendered_json_ld_is_valid_localized_and_exact(self):
        cases = (
            (reverse("home"), "WebSite"),
            (
                reverse(
                    "articles:article_detail",
                    args=[self.public_article.slug],
                ),
                "Article",
            ),
            (
                reverse("videos:detail", args=[self.public_video.slug]),
                "VideoObject",
            ),
            (
                reverse("shop:detail", args=[self.product.slug]),
                "Product",
            ),
        )
        for url, schema_type in cases:
            with self.subTest(url=url):
                response = self.client.get(url, secure=True)
                payload = self.json_ld(response)
                self.assertEqual(payload["@context"], "https://schema.org")
                self.assertEqual(payload["@type"], schema_type)
                self.assertTrue(payload["url"].startswith("https://testserver/"))
                self.assertEqual(payload["inLanguage"], "fr")

        product_payload = self.json_ld(
            self.client.get(
                f"/en/shop/produit/{self.product.slug}/",
                secure=True,
            )
        )
        self.assertEqual(product_payload["name"], self.product.nom_en)
        self.assertNotIn("offers", product_payload)
        self.assertNotIn("aggregateRating", product_payload)

    def test_json_ld_serialization_blocks_script_injection(self):
        unsafe = Article.objects.create(
            titre="</script><script>alert('schema')</script>",
            contenu="Contenu public.",
            slug="article-schema-injection-audit",
        )
        response = self.client.get(
            reverse("articles:article_detail", args=[unsafe.slug]),
            secure=True,
        )
        markup = response.content.decode()

        self.assertEqual(markup.count('id="structured-data"'), 1)
        self.assertNotIn("</script><script>alert", markup)
        self.assertEqual(self.json_ld(response)["headline"], unsafe.titre)

    def test_robots_allows_noindex_payment_pages_and_blocks_machine_endpoints(self):
        response = self.client.get(reverse("robots_txt"), secure=True)
        content = response.content.decode()

        self.assertNotIn("Disallow: /payments/\n", content)
        self.assertIn("Disallow: /payments/webhook/", content)
        self.assertIn("Disallow: /payments/cinetpay/ipn/", content)
        payment_page = self.client.get(reverse("payments:success"))
        self.assertContains(
            payment_page,
            '<meta name="robots" content="noindex,follow">',
        )

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_unapproved_host_cannot_influence_absolute_metadata(self):
        response = self.client.get("/", HTTP_HOST="attacker.example")
        self.assertEqual(response.status_code, 400)

    def test_global_assets_are_not_duplicated_or_loaded_without_need(self):
        response = self.client.get(reverse("home"))
        markup = response.content.decode()
        head = markup.split("</head>", 1)[0]
        asset_urls = re.findall(
            r'<(?:script\b[^>]*\bsrc|'
            r'link\b(?=[^>]*\brel="stylesheet")[^>]*\bhref)="([^"]+)"',
            head,
        )

        self.assertEqual(len(asset_urls), len(set(asset_urls)))
        self.assertNotIn("/static/js/stripe.js", markup)
        styles = (Path(settings.BASE_DIR) / "static" / "css" / "styles.css").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("@import", styles)
        self.assertContains(
            response,
            "https://fonts.googleapis.com/css2?family=DM+Sans",
            count=1,
        )
        for script_tag in re.findall(r"<script[^>]+src=[^>]+>", head):
            self.assertIn("defer", script_tag)

        about = self.client.get(reverse("about"))
        self.assertContains(
            about,
            'src="/static/images/logo.webp" alt="Logo Teyilawson" width="1024" height="1024"',
        )

    def test_private_pages_are_not_marked_for_shared_caching(self):
        self.client.force_login(self.free_user)
        for url in (
            reverse("accounts:profile"),
            reverse("shop:panier"),
            reverse("shop:mes_commandes"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn("Cookie", response.get("Vary", ""))
                self.assertNotIn("public", response.get("Cache-Control", "").lower())


class PublicQueryBudgetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        article_category = CategorieArticle.objects.create(
            nom="Catégorie SQL",
            slug="categorie-sql-audit",
        )
        product_category = Categorie.objects.create(
            nom="Catalogue SQL",
            slug="catalogue-sql-audit",
        )
        partner = Partenaire.objects.create(nom="Partenaire SQL")
        for index in range(15):
            Article.objects.create(
                titre=f"Article SQL {index}",
                contenu=f"Contenu SQL {index}",
                slug=f"article-sql-{index}",
                categorie=article_category,
                en_vedette=index == 0,
            )
            Video.objects.create(
                titre=f"Vidéo SQL {index}",
                description=f"Description SQL {index}",
                slug=f"video-sql-{index}",
                youtube_url=f"https://youtu.be/{YOUTUBE_ID}",
                est_publie=True,
                categorie=article_category,
                en_vedette=index == 0,
            )
            Produit.objects.create(
                nom=f"Produit SQL {index}",
                slug=f"produit-sql-{index}",
                prix=Decimal("10.00"),
                categorie=product_category,
                en_vedette=index < 6,
            )
            Publicite.objects.create(
                titre=f"Campagne SQL {index}",
                partenaire=partner,
                image=f"publicites/sql-{index}.jpg",
                lien=f"https://example.test/sql-{index}",
                ordre=index,
            )
        cls.product_category = product_category

    def query_count(self, url):
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return len(captured), response

    def test_public_page_query_counts_are_bounded(self):
        expected_maximums = {
            reverse("home"): 4,
            reverse("articles:articles"): 3,
            reverse("videos:list"): 3,
            reverse("shop:liste"): 3,
            reverse("monetization:abonnements"): 1,
            reverse("monetization:publicites"): 1,
        }
        for url, maximum in expected_maximums.items():
            with self.subTest(url=url):
                count, _response = self.query_count(url)
                self.assertLessEqual(count, maximum)

    def test_category_products_are_paginated_with_a_bounded_query_count(self):
        url = reverse(
            "shop:par_categorie",
            args=[self.product_category.slug],
        )
        first_count, first_page = self.query_count(url)
        second_count, second_page = self.query_count(f"{url}?page=2")

        self.assertLessEqual(first_count, 4)
        self.assertLessEqual(second_count, 4)
        self.assertEqual(len(first_page.context["produits"]), 12)
        self.assertEqual(len(second_page.context["produits"]), 3)
        self.assertEqual(first_page.context["paginator"].count, 15)
        self.assertTrue(first_page.context["paginator"].object_list.ordered)
