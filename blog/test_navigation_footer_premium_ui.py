from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from shop.context_processors import panier_counter
from shop.models import Cart, CartItem, Produit


class FooterLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_footer = False
        self.links = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "footer":
            self.in_footer = True
        elif self.in_footer and tag == "a":
            self.links.append(attributes.get("href", ""))

    def handle_endtag(self, tag):
        if tag == "footer":
            self.in_footer = False


class NavigationFooterPremiumUITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="reader-navigation@example.test",
            password="test-password",
        )
        cls.staff = get_user_model().objects.create_user(
            email="staff-navigation@example.test",
            password="test-password",
            is_staff=True,
        )

    def setUp(self):
        translation.activate("fr")
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "fr"
        self.addCleanup(translation.deactivate)

    def test_primary_links_keep_the_expected_order(self):
        markup = self.client.get(reverse("home")).content.decode()
        panel_start = markup.index('data-site-navigation-panel')
        labels = ("Accueil", "Articles", "Vidéos", "Boutique", "À propos", "Contact")
        positions = [markup.index(f">{label}</a>", panel_start) for label in labels]

        self.assertEqual(positions, sorted(positions))

    def test_active_page_is_exposed_visually_and_semantically(self):
        routes = (
            (reverse("home"), 'class="nav-link is-current" aria-current="page" href="/"'),
            (
                reverse("articles:articles"),
                'class="nav-link is-current" aria-current="page" href="/articles/"',
            ),
            (
                reverse("shop:liste"),
                'class="nav-link is-current" aria-current="page" href="/shop/"',
            ),
        )

        for url, marker in routes:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, marker, count=1)
                self.assertContains(response, 'aria-current="page"', count=1)

    def test_mobile_menu_markup_is_accessible_without_javascript(self):
        response = self.client.get(reverse("home"))

        self.assertContains(
            response,
            'aria-controls="mainNavigation" aria-expanded="false"',
        )
        self.assertContains(response, 'data-site-navigation-toggle hidden')
        self.assertContains(
            response,
            '<div class="site-navigation-panel" id="mainNavigation" data-site-navigation-panel>',
        )
        self.assertNotContains(response, 'data-bs-target="#mainNavigation"')
        self.assertContains(response, "js/site-navigation.js")

    def test_anonymous_authenticated_and_staff_actions_are_preserved(self):
        anonymous = self.client.get(reverse("home"))
        self.assertContains(anonymous, reverse("accounts:login"), count=2)
        self.assertContains(anonymous, reverse("accounts:register"), count=2)

        self.client.force_login(self.user)
        authenticated = self.client.get(reverse("home"))
        self.assertContains(authenticated, reverse("accounts:profile"), count=2)
        self.assertContains(authenticated, reverse("shop:mes_commandes"), count=2)
        self.assertNotContains(authenticated, reverse("monetization:revenus"))

        self.client.force_login(self.staff)
        staff = self.client.get(reverse("home"))
        self.assertContains(staff, reverse("monetization:revenus"))

    def test_logout_remains_a_csrf_protected_post_action(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        page = csrf_client.get(reverse("home"))
        token = csrf_client.cookies[settings.CSRF_COOKIE_NAME].value

        self.assertContains(
            page,
            f'<form method="post" action="{reverse("accounts:logout")}">',
        )
        self.assertEqual(csrf_client.get(reverse("accounts:logout")).status_code, 405)
        self.assertEqual(csrf_client.post(reverse("accounts:logout")).status_code, 403)
        response = csrf_client.post(
            reverse("accounts:logout"),
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 302)

    def test_cart_counter_query_count_is_constant_with_many_items(self):
        cart = Cart.objects.create(user=self.user)
        products = [
            Produit.objects.create(
                nom=f"Produit navigation {index}",
                slug=f"produit-navigation-{index}",
                prix=Decimal("10.00"),
            )
            for index in range(12)
        ]
        CartItem.objects.bulk_create(
            [
                CartItem(
                    cart=cart,
                    produit=product,
                    quantite=1,
                    prix_unitaire=product.prix,
                )
                for product in products
            ]
        )
        request = RequestFactory().get("/")
        request.user = self.user

        with self.assertNumQueries(2):
            context = panier_counter(request)

        self.assertEqual(context["panier_items_count"], 12)

    def test_footer_contains_only_real_internal_destinations(self):
        markup = self.client.get(reverse("home")).content.decode()
        parser = FooterLinkParser()
        parser.feed(markup)

        self.assertTrue(parser.links)
        self.assertTrue(all(link.startswith(("/", "#")) for link in parser.links))
        self.assertFalse(any(link.lower().startswith("javascript:") for link in parser.links))
        for fake_provider in ("facebook.com", "instagram.com", "linkedin.com", "youtube.com"):
            self.assertNotIn(fake_provider, markup)

    @patch("blog.views.EmailMessage.send", return_value=1)
    @override_settings(
        CONTACT_EMAIL="contact@example.test",
        DEFAULT_FROM_EMAIL="noreply@example.test",
    )
    def test_success_messages_use_a_polite_status_without_auto_dismiss(self, send):
        response = self.client.post(
            reverse("contact"),
            {
                "prenom": "Ada",
                "nom": "Lovelace",
                "email": "ada@example.test",
                "message": "Bonjour",
            },
            follow=True,
        )

        self.assertEqual(send.call_count, 1)
        self.assertContains(
            response,
            'role="status" aria-live="polite" aria-atomic="true"',
        )
        self.assertNotContains(response, "data-bs-delay")


class NavigationFooterStaticContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base_dir = Path(settings.BASE_DIR)
        cls.template = (base_dir / "templates" / "template_base.html").read_text(
            encoding="utf-8"
        )
        cls.styles = (base_dir / "static" / "css" / "styles.css").read_text(
            encoding="utf-8"
        )

    def test_child_extension_blocks_remain_available(self):
        self.assertIn("{% block styles %}", self.template)
        self.assertIn("{% block scripts %}", self.template)
        self.assertIn("{% block contenu %}{% block content %}", self.template)
        self.assertIn("{% block extra_js %}", self.template)

    def test_navigation_styles_use_tokens_and_no_new_important_override(self):
        start = self.styles.index(".site-header {")
        end = self.styles.index(".site-main {")
        navigation_styles = self.styles[start:end]

        self.assertNotIn("!important", navigation_styles)
        self.assertIn("min-height: 2.75rem", navigation_styles)
        self.assertIn("box-shadow: inset 0 -3px 0", navigation_styles)
        self.assertNotIn("overflow-x: hidden", self.styles)
