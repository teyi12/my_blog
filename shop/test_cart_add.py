import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from shop.models import Categorie, Cart, CartItem, Produit


class AddToCartTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="cart@example.com",
            password="test-password",
        )
        cls.category = Categorie.objects.create(nom="Livres", slug="livres")
        cls.product = Produit.objects.create(
            nom="Produit test",
            slug="produit-test",
            prix=Decimal("12.50"),
            categorie=cls.category,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.add_url = reverse("shop:ajouter_panier", args=[self.product.slug])

    def test_get_is_rejected_with_405_without_creating_cart_or_item(self):
        response = self.client.get(self.add_url)

        self.assertEqual(response.status_code, 405)
        self.assertFalse(Cart.objects.exists())
        self.assertFalse(CartItem.objects.exists())

    def test_get_does_not_change_an_existing_item_quantity(self):
        cart = Cart.objects.create(user=self.user)
        item = CartItem.objects.create(cart=cart, produit=self.product, quantite=2)

        response = self.client.get(self.add_url)

        self.assertEqual(response.status_code, 405)
        item.refresh_from_db()
        self.assertEqual(item.quantite, 2)
        self.assertEqual(Cart.objects.count(), 1)
        self.assertEqual(CartItem.objects.count(), 1)

    def test_valid_post_creates_cart_and_line_then_redirects_to_cart(self):
        response = self.client.post(self.add_url)

        cart = Cart.objects.get(user=self.user)
        item = CartItem.objects.get(cart=cart, produit=self.product)
        self.assertEqual(item.quantite, 1)
        self.assertRedirects(response, reverse("shop:panier"))

    def test_post_increments_an_existing_line(self):
        cart = Cart.objects.create(user=self.user)
        item = CartItem.objects.create(cart=cart, produit=self.product, quantite=2)

        response = self.client.post(self.add_url)

        self.assertRedirects(response, reverse("shop:panier"))
        item.refresh_from_db()
        self.assertEqual(item.quantite, 3)
        self.assertEqual(CartItem.objects.filter(cart=cart).count(), 1)

    def test_unknown_product_returns_404_without_creating_cart(self):
        response = self.client.post(
            reverse("shop:ajouter_panier", args=["produit-inexistant"])
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Cart.objects.exists())
        self.assertFalse(CartItem.objects.exists())

    def test_post_without_csrf_token_is_rejected(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post(self.add_url)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Cart.objects.exists())
        self.assertFalse(CartItem.objects.exists())

    def test_valid_internal_next_redirect_is_used(self):
        internal_url = reverse("shop:detail", args=[self.product.slug])

        response = self.client.post(self.add_url, {"next": internal_url})

        self.assertRedirects(response, internal_url)

    def test_external_next_redirect_is_rejected(self):
        response = self.client.post(
            self.add_url,
            {"next": "https://example.org/collect"},
        )

        self.assertRedirects(response, reverse("shop:panier"))

    def test_all_add_buttons_are_post_forms_with_csrf_tokens(self):
        urls = [
            reverse("shop:liste"),
            reverse("shop:par_categorie", args=[self.category.slug]),
            reverse("shop:detail", args=[self.product.slug]),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                escaped_action = re.escape(self.add_url)
                self.assertRegex(
                    html,
                    rf'<form method="post" action="{escaped_action}">',
                )
                self.assertRegex(
                    html,
                    r'<input type="hidden" name="csrfmiddlewaretoken" value="[^"]+">',
                )
                self.assertRegex(html, r'<button[^>]+type="submit"')

