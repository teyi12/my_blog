import re
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation

from .models import Cart, CartItem, Produit


class FormStructureParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.form_depth = 0
        self.nested_forms = 0
        self.h1_count = 0

    def handle_starttag(self, tag, attrs):
        if tag == "form":
            if self.form_depth:
                self.nested_forms += 1
            self.form_depth += 1
        elif tag == "h1":
            self.h1_count += 1

    def handle_endtag(self, tag):
        if tag == "form":
            self.form_depth -= 1


class CartCheckoutPremiumUITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="cart-checkout-ui@example.test",
            password="test-password",
        )
        cls.product = Produit.objects.create(
            nom_fr="Carnet <édition>",
            nom_de="Notizbuch Sonderausgabe",
            nom_en="Limited notebook",
            slug="carnet-cart-checkout-ui",
            prix=Decimal("18.50"),
            stock=5,
            image="produits/cart-checkout-ui.jpg",
        )

    def setUp(self):
        translation.activate("fr")
        self.addCleanup(translation.deactivate)
        self.client.force_login(self.user)
        self.cart = Cart.objects.create(user=self.user)
        self.item = CartItem.objects.create(
            cart=self.cart,
            produit=self.product,
            quantite=1,
            prix_unitaire=self.product.prix,
        )

    def test_cart_uses_separate_post_forms_sized_images_and_one_h1(self):
        response = self.client.get(reverse("shop:panier"))
        markup = response.content.decode()
        parser = FormStructureParser()
        parser.feed(markup)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(parser.h1_count, 1)
        self.assertEqual(parser.nested_forms, 0)
        self.assertContains(response, 'class="cart-quantity-form cart-action-form"')
        self.assertContains(response, 'class="cart-remove-form cart-action-form"')
        self.assertContains(response, 'method="post"', count=4)
        self.assertContains(response, 'width="320" height="320" loading="lazy"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertNotIn("<script>alert", markup)
        self.assertIn("Carnet &lt;édition&gt;", markup)

    def test_cart_forms_work_without_javascript_and_get_cannot_mutate(self):
        update_url = reverse("shop:update_panier")

        get_response = self.client.get(update_url)
        update_response = self.client.post(
            update_url,
            {
                "action": "modifier",
                "item_id": self.item.pk,
                "quantite": "3",
            },
        )
        self.item.refresh_from_db()

        self.assertEqual(get_response.status_code, 405)
        self.assertRedirects(update_response, reverse("shop:panier"))
        self.assertEqual(self.item.quantite, 3)
        self.assertEqual(self.cart.total(), Decimal("55.50"))

        remove_response = self.client.post(
            update_url,
            {"action": "supprimer", "item_id": self.item.pk},
        )
        self.assertRedirects(remove_response, reverse("shop:panier"))
        self.assertFalse(CartItem.objects.filter(pk=self.item.pk).exists())

    def test_cart_mutations_keep_csrf_protection(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(
            reverse("shop:update_panier"),
            {"action": "supprimer", "item_id": self.item.pk},
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(CartItem.objects.filter(pk=self.item.pk).exists())

    def test_non_javascript_stock_error_keeps_the_existing_quantity(self):
        response = self.client.post(
            reverse("shop:update_panier"),
            {
                "action": "modifier",
                "item_id": self.item.pk,
                "quantite": "8",
            },
            follow=True,
        )
        self.item.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Stock insuffisant")
        self.assertEqual(self.item.quantite, 1)

    def test_empty_cart_uses_shared_empty_state(self):
        self.item.delete()
        response = self.client.get(reverse("shop:panier"))

        self.assertContains(response, 'class="empty-state cart-empty"')
        self.assertContains(response, reverse("shop:liste"))
        self.assertEqual(response.content.decode().count("<h1"), 1)

    def test_cart_rendering_does_not_add_queries_per_item(self):
        with CaptureQueriesContext(connection) as single_item_queries:
            self.client.get(reverse("shop:panier"))

        for position in range(4):
            product = Produit.objects.create(
                nom=f"Produit supplémentaire {position}",
                slug=f"produit-supplementaire-ui-{position}",
                prix=Decimal("3.00"),
            )
            CartItem.objects.create(
                cart=self.cart,
                produit=product,
                prix_unitaire=product.prix,
            )

        with CaptureQueriesContext(connection) as multiple_item_queries:
            self.client.get(reverse("shop:panier"))

        self.assertLessEqual(
            len(multiple_item_queries),
            len(single_item_queries) + 1,
        )

    def test_checkout_errors_are_linked_and_values_are_preserved(self):
        checkout_url = reverse("shop:checkout")
        token = self.client.get(checkout_url).context["checkout_token"]
        response = self.client.post(
            checkout_url,
            {
                "checkout_token": str(token),
                "rue": "123 rue très longue",
                "ville": "",
                "code_postal": "",
                "pays": "",
                "telephone": "0123456789",
            },
        )
        markup = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(markup.count("<h1"), 1)
        self.assertContains(response, 'role="alert" aria-labelledby="checkout-errors-title"')
        self.assertContains(response, 'href="#id_ville"')
        self.assertContains(response, 'name="ville"')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, 'aria-describedby="id_ville_error"')
        self.assertContains(response, 'value="123 rue très longue"')
        self.assertNotContains(response, ">Gratuite<")
        self.assertNotContains(response, ">Livraison<")

    def test_checkout_keeps_address_collection_for_physical_digital_and_mixed_carts(self):
        digital = Produit.objects.create(
            nom="Guide numérique",
            slug="guide-numerique-checkout-ui",
            prix=Decimal("9.00"),
            fichier="produits/fichiers/guide.pdf",
        )
        cases = (
            [self.product],
            [digital],
            [self.product, digital],
        )

        for products in cases:
            with self.subTest(products=[product.slug for product in products]):
                self.cart.items.all().delete()
                for product in products:
                    CartItem.objects.create(
                        cart=self.cart,
                        produit=product,
                        prix_unitaire=product.prix,
                    )
                response = self.client.get(reverse("shop:checkout"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'action="{}"'.format(reverse("shop:checkout")))
                self.assertContains(response, 'name="rue"')

    def test_anonymous_users_are_redirected_from_cart_and_checkout(self):
        self.client.logout()
        for url in (reverse("shop:panier"), reverse("shop:checkout")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response.url)


class CartCheckoutPremiumUIStaticTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = Path(settings.BASE_DIR)
        cls.styles = (base / "static/css/styles.css").read_text(encoding="utf-8")
        cls.page_css = "\n".join(
            (base / path).read_text(encoding="utf-8")
            for path in ("static/css/cart.css", "static/css/checkout.css")
        )
        cls.cart_template = (
            base / "shop/templates/shop/panier.html"
        ).read_text(encoding="utf-8")

    def test_page_css_uses_defined_tokens_and_no_important(self):
        all_css = self.styles + "\n" + self.page_css
        used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", self.page_css, re.I))
        defined = set(
            re.findall(r"(--[a-z0-9-]+)\s*:\s*[^;{}]+;", all_css, re.I)
        )

        self.assertEqual(used - defined, set())
        self.assertNotIn("!important", self.page_css)
        self.assertIsNone(re.search(r"#[0-9a-f]{3,8}\b", self.page_css, re.I))
        self.assertIsNone(re.search(r"\brgba?\(", self.page_css, re.I))

    def test_responsive_reduced_motion_and_external_script_are_present(self):
        for marker in (
            "@media (max-width: 1099.98px)",
            "@media (max-width: 991.98px)",
            "@media (max-width: 767.98px)",
            "@media (max-width: 419.98px)",
            "@media (prefers-reduced-motion: reduce)",
        ):
            self.assertIn(marker, self.page_css)
        self.assertIn("static 'js/cart.js'", self.cart_template)
        self.assertNotIn("onclick=", self.cart_template)
        self.assertNotIn("onchange=", self.cart_template)
        self.assertNotRegex(self.cart_template, r"\|safe\b")
