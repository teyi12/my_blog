from types import SimpleNamespace
from xml.etree import ElementTree

from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import translation

from articles.models import Article
from payments.models import Adresse
from shop.models import Cart, CartItem, Commande, LigneCommande, Produit
from videos.models import Video

from .seo import available_translation_languages, social_image_url


YOUTUBE_ID = "dQw4w9WgXcQ"


class SeoMetadataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.translated_article = Article.objects.create(
            titre_fr="Voyage & culture",
            titre_de="Reise & Kultur",
            titre_en="Travel & culture",
            contenu_fr="<p>Un récit français riche en découvertes.</p>",
            contenu_de="<p>Ein deutscher Reisebericht.</p>",
            contenu_en="<p>An English travel story.</p>",
            slug="voyage-culture",
            image="articles/social.jpg",
        )
        cls.fallback_article = Article.objects.create(
            titre_fr="Titre <script>alert(1)</script>",
            titre_de="",
            titre_en="",
            contenu_fr="<p>Description <strong>française</strong>.</p>",
            contenu_de="",
            contenu_en="",
            slug="article-francais",
        )
        cls.product = Produit.objects.create(
            nom_fr="Produit français",
            nom_de="Deutsches Produkt",
            nom_en="English product",
            description_fr="Description française",
            description_de="Deutsche Beschreibung",
            description_en="English description",
            slug="produit-multilingue",
            prix="12.00",
        )
        cls.video = Video.objects.create(
            titre_fr="Vidéo française",
            titre_de="Deutsches Video",
            titre_en="English video",
            description_fr="Description française",
            description_de="Deutsche Beschreibung",
            description_en="English description",
            slug="video-multilingue",
            youtube_url=f"https://www.youtube.com/watch?v={YOUTUBE_ID}",
            est_publie=True,
        )

    def setUp(self):
        translation.activate("fr")

    def tearDown(self):
        translation.deactivate()

    def test_static_page_has_single_title_and_description(self):
        response = self.client.get(reverse("home"), secure=True)
        html = response.content.decode()

        self.assertEqual(html.count("<title>"), 1)
        self.assertEqual(html.count('<meta name="description"'), 1)
        self.assertContains(response, '<meta name="robots" content="index,follow">')

    def test_static_canonicals_follow_language_and_drop_query_parameters(self):
        expected = {
            "/?utm_source=test&page=2": "https://testserver/",
            "/articles/?page=2&utm_campaign=test": "https://testserver/articles/",
            "/de/about/?utm_source=test": "https://testserver/de/about/",
            "/en/about/?page=2": "https://testserver/en/about/",
        }
        for url, canonical in expected.items():
            with self.subTest(url=url):
                response = self.client.get(url, secure=True)
                self.assertContains(
                    response,
                    f'<link rel="canonical" href="{canonical}">',
                )

    def test_static_alternates_are_reciprocal_with_french_x_default(self):
        expected = {
            "fr": ("/about/", "https://testserver/about/"),
            "de": ("/de/about/", "https://testserver/de/about/"),
            "en": ("/en/about/", "https://testserver/en/about/"),
        }
        for language, (url, canonical) in expected.items():
            with self.subTest(language=language):
                response = self.client.get(url, secure=True)
                self.assertContains(response, f'hreflang="fr" href="https://testserver/about/"')
                self.assertContains(response, f'hreflang="de" href="https://testserver/de/about/"')
                self.assertContains(response, f'hreflang="en" href="https://testserver/en/about/"')
                self.assertContains(response, f'hreflang="x-default" href="https://testserver/about/"')
                self.assertContains(response, f'<meta property="og:url" content="{canonical}">')

    def test_real_dynamic_translation_is_indexable(self):
        response = self.client.get(
            f"/de/articles/{self.translated_article.slug}/",
            secure=True,
        )

        self.assertContains(response, '<meta name="robots" content="index,follow">')
        self.assertContains(
            response,
            f'<link rel="canonical" href="https://testserver/de/articles/{self.translated_article.slug}/">',
        )
        self.assertContains(response, 'hreflang="de"')
        self.assertContains(response, "Ein deutscher Reisebericht.")

    def test_dynamic_french_fallback_is_noindex_and_canonical_french(self):
        response = self.client.get(
            f"/de/articles/{self.fallback_article.slug}/",
            secure=True,
        )

        self.assertContains(response, '<meta name="robots" content="noindex,follow">')
        self.assertContains(
            response,
            f'<link rel="canonical" href="https://testserver/articles/{self.fallback_article.slug}/">',
        )
        self.assertContains(response, 'hreflang="fr"')
        self.assertNotContains(response, 'hreflang="de"')
        self.assertNotContains(response, 'hreflang="en"')

    def test_database_metadata_is_plain_text_and_html_escaped(self):
        response = self.client.get(
            f"/articles/{self.fallback_article.slug}/",
            secure=True,
        )

        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "Titre &lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertContains(response, 'content="Description française."')
        self.assertNotContains(response, 'content="<p>Description')

    def test_open_graph_and_twitter_metadata_use_https_fallback_image(self):
        response = self.client.get(reverse("home"), secure=True)

        self.assertContains(response, '<meta property="og:title"')
        self.assertContains(response, '<meta property="og:description"')
        self.assertContains(response, '<meta property="og:type" content="website">')
        self.assertContains(response, '<meta property="og:locale" content="fr_FR">')
        self.assertContains(response, '<meta property="og:site_name" content="Teyilawson">')
        self.assertContains(response, '<meta name="twitter:card" content="summary_large_image">')
        self.assertContains(response, '<meta name="twitter:title"')
        self.assertContains(response, '<meta name="twitter:description"')
        self.assertContains(response, '<meta name="twitter:image" content="https://testserver/static/images/home-hero.jpg">')

    def test_cloudinary_image_is_normalized_to_absolute_https(self):
        request = RequestFactory().get("/", secure=True, HTTP_HOST="testserver")
        image = SimpleNamespace(
            name="articles/cloudinary.jpg",
            url="http://res.cloudinary.com/demo/image/upload/cloudinary.jpg",
        )

        self.assertEqual(
            social_image_url(request, image),
            "https://res.cloudinary.com/demo/image/upload/cloudinary.jpg",
        )

    def test_translation_availability_reads_explicit_columns(self):
        self.assertEqual(
            available_translation_languages(
                self.translated_article,
                ("titre", "contenu"),
            ),
            ("fr", "de", "en"),
        )
        self.assertEqual(
            available_translation_languages(
                self.fallback_article,
                ("titre", "contenu"),
            ),
            ("fr",),
        )


class PrivatePageRobotsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="seo-private@example.com",
            password="test-password",
        )
        cls.product = Produit.objects.create(
            nom="Produit privé",
            slug="produit-prive",
            prix="10.00",
        )
        cls.cart = Cart.objects.create(user=cls.user)
        cls.cart_item = CartItem.objects.create(
            cart=cls.cart,
            produit=cls.product,
            prix_unitaire=cls.product.prix,
        )
        cls.address = Adresse.objects.create(
            utilisateur=cls.user,
            rue="1 rue SEO",
            ville="Paris",
            code_postal="75001",
            pays="France",
        )
        cls.order = Commande.objects.create(
            client=cls.user,
            adresse=cls.address,
            source_cart=cls.cart,
            total="10.00",
        )
        LigneCommande.objects.create(
            commande=cls.order,
            produit=cls.product,
            source_cart_item=cls.cart_item,
            quantite=1,
            prix_unitaire="10.00",
        )

    def test_account_pages_are_noindex(self):
        for url in (reverse("accounts:login"), reverse("accounts:register")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, '<meta name="robots" content="noindex,follow">')

        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, '<meta name="robots" content="noindex,follow">')

    def test_cart_checkout_order_and_payment_pages_are_noindex(self):
        self.client.force_login(self.user)
        urls = (
            reverse("shop:panier"),
            reverse("shop:checkout"),
            reverse("shop:mes_commandes"),
            reverse("payments:choice", args=[self.order.pk]),
            reverse("payments:success"),
            reverse("payments:cancel"),
            reverse("monetization:don"),
        )
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '<meta name="robots" content="noindex,follow">')


class SitemapAndRobotsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Site.objects.update_or_create(
            pk=1,
            defaults={"domain": "testserver", "name": "Teyilawson tests"},
        )
        cls.public_article = Article.objects.create(
            titre_fr="Article public",
            titre_de="Öffentlicher Artikel",
            titre_en="Public article",
            contenu_fr="Contenu public",
            contenu_de="Öffentlicher Inhalt",
            contenu_en="Public content",
            slug="article-public",
        )
        cls.french_only_article = Article.objects.create(
            titre_fr="Article français",
            titre_de="",
            titre_en="",
            contenu_fr="Contenu français",
            contenu_de="",
            contenu_en="",
            slug="article-francais-sitemap",
        )
        cls.premium_article = Article.objects.create(
            titre_fr="Article Premium",
            contenu_fr="Contenu Premium",
            slug="article-premium",
            is_premium=True,
        )
        cls.product = Produit.objects.create(
            nom_fr="Produit public",
            description_fr="Description publique",
            slug="produit-public",
            prix="10.00",
        )
        cls.public_video = Video.objects.create(
            titre_fr="Vidéo publique",
            description_fr="Description publique",
            slug="video-publique-seo",
            youtube_url=f"https://youtu.be/{YOUTUBE_ID}",
            est_publie=True,
        )
        cls.premium_video = Video.objects.create(
            titre_fr="Vidéo Premium",
            description_fr="Description Premium",
            slug="video-premium-seo",
            youtube_url=f"https://youtu.be/{YOUTUBE_ID}",
            est_publie=True,
            is_premium=True,
        )
        cls.draft_video = Video.objects.create(
            titre_fr="Vidéo brouillon",
            description_fr="Description brouillon",
            slug="video-brouillon-seo",
            youtube_url=f"https://youtu.be/{YOUTUBE_ID}",
            est_publie=False,
        )

    def test_sitemap_is_valid_https_xml_with_public_content_only(self):
        response = self.client.get(reverse("sitemap"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/xml"))
        ElementTree.fromstring(response.content)
        xml = response.content.decode()
        self.assertIn("https://testserver/", xml)
        self.assertIn(f"https://testserver/articles/{self.public_article.slug}/", xml)
        self.assertIn(f"https://testserver/shop/produit/{self.product.slug}/", xml)
        self.assertIn(f"https://testserver/videos/{self.public_video.slug}/", xml)
        self.assertNotIn(self.premium_article.slug, xml)
        self.assertNotIn(self.premium_video.slug, xml)
        self.assertNotIn(self.draft_video.slug, xml)
        for private_path in (
            "/admin/",
            "/accounts/",
            "/shop/panier/",
            "/shop/checkout/",
            "/payments/",
        ):
            self.assertNotIn(private_path, xml)

    def test_sitemap_has_multilingual_alternates_only_for_real_translations(self):
        response = self.client.get(reverse("sitemap"))
        xml = response.content.decode()

        self.assertIn(f"https://testserver/de/articles/{self.public_article.slug}/", xml)
        self.assertIn(f"https://testserver/en/articles/{self.public_article.slug}/", xml)
        self.assertNotIn(f"/de/articles/{self.french_only_article.slug}/", xml)
        self.assertNotIn(f"/en/articles/{self.french_only_article.slug}/", xml)
        self.assertIn('hreflang="x-default"', xml)

    def test_robots_txt_is_plain_text_with_absolute_sitemap_and_exclusions(self):
        response = self.client.get(reverse("robots_txt"))
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/plain"))
        self.assertIn("User-agent: *", content)
        self.assertIn("Allow: /", content)
        self.assertIn("Sitemap: https://testserver/sitemap.xml", content)
        self.assertIn("Disallow: /admin/", content)
        self.assertIn("Disallow: /payments/", content)
        self.assertIn("Disallow: /i18n/", content)
        self.assertNotIn("Disallow: /static/", content)
        self.assertNotIn("Disallow: /accounts/", content)

    def test_sitemap_and_robots_are_not_localized(self):
        for url in (
            "/de/sitemap.xml",
            "/en/sitemap.xml",
            "/de/robots.txt",
            "/en/robots.txt",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_payment_callback_urls_are_unchanged(self):
        self.assertEqual(reverse("payments:stripe_webhook"), "/payments/webhook/")
        self.assertEqual(reverse("payments:cinetpay_return"), "/payments/cinetpay/return/")
        self.assertEqual(reverse("payments:cinetpay_cancel"), "/payments/cinetpay/cancel/")
        self.assertEqual(reverse("payments:cinetpay_ipn"), "/payments/cinetpay/ipn/")
