import json
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase
from django.urls import reverse

from shop.context_processors import panier_counter
from shop.models import Cart, CartItem, Commande, Produit
from shop.services import get_or_create_active_cart


class CartIntegrityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="integrity@example.com",
            password="test-password",
        )
        cls.product = Produit.objects.create(
            nom="Produit actif",
            slug="produit-actif",
            prix=Decimal("15.00"),
        )
        cls.other_product = Produit.objects.create(
            nom="Produit historique",
            slug="produit-historique",
            prix=Decimal("20.00"),
        )

    def test_service_creates_then_reuses_active_cart(self):
        created = get_or_create_active_cart(self.user)
        reused = get_or_create_active_cart(self.user)

        self.assertEqual(created, reused)
        self.assertTrue(created.actif)
        self.assertEqual(Cart.objects.filter(user=self.user).count(), 1)

    def test_two_active_carts_for_same_user_are_forbidden(self):
        Cart.objects.create(user=self.user, actif=True)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Cart.objects.create(user=self.user, actif=True)

    def test_historical_inactive_carts_are_allowed(self):
        active = Cart.objects.create(user=self.user, actif=True)
        first_history = Cart.objects.create(user=self.user, actif=False)
        second_history = Cart.objects.create(user=self.user, actif=False)

        self.assertTrue(active.actif)
        self.assertEqual(
            Cart.objects.filter(user=self.user, actif=False).count(),
            2,
        )
        self.assertNotEqual(first_history, second_history)

    def test_multiple_anonymous_active_carts_are_allowed(self):
        Cart.objects.create(user=None, actif=True)
        Cart.objects.create(user=None, actif=True)

        self.assertEqual(Cart.objects.filter(user=None, actif=True).count(), 2)

    def test_product_is_unique_inside_cart(self):
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, produit=self.product)

        with self.assertRaises(IntegrityError), transaction.atomic():
            CartItem.objects.create(cart=cart, produit=self.product)

    def test_service_recovers_cart_created_by_concurrent_request(self):
        concurrent_cart = Cart.objects.create(user=self.user)

        with patch.object(
            Cart.objects,
            "filter",
        ) as filtered, patch.object(Cart.objects, "create") as create, patch.object(
            Cart.objects,
            "get",
            return_value=concurrent_cart,
        ) as get:
            filtered.return_value.first.return_value = None
            create.side_effect = IntegrityError("concurrent insert")

            result = get_or_create_active_cart(self.user)

        self.assertEqual(result, concurrent_cart)
        get.assert_called_once_with(user=self.user, actif=True)

    def test_cart_view_addition_and_context_processor_use_active_cart(self):
        historical = Cart.objects.create(user=self.user, actif=False)
        active = Cart.objects.create(user=self.user, actif=True)
        CartItem.objects.create(
            cart=historical,
            produit=self.other_product,
            quantite=4,
        )
        self.client.force_login(self.user)

        cart_response = self.client.get(reverse("shop:panier"))
        add_response = self.client.post(
            reverse("shop:ajouter_panier", args=[self.product.slug])
        )

        self.assertEqual(cart_response.context["cart"], active)
        self.assertRedirects(add_response, reverse("shop:panier"))
        self.assertTrue(active.items.filter(produit=self.product).exists())
        self.assertFalse(historical.items.filter(produit=self.product).exists())

        request = RequestFactory().get("/")
        request.user = self.user
        self.assertEqual(panier_counter(request)["panier_items_count"], 1)

    def test_quantity_update_cannot_target_historical_cart(self):
        historical = Cart.objects.create(user=self.user, actif=False)
        Cart.objects.create(user=self.user, actif=True)
        item = CartItem.objects.create(
            cart=historical,
            produit=self.product,
            quantite=4,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("shop:update_panier"),
            data=json.dumps(
                {"action": "modifier", "item_id": item.id, "quantite": 9}
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        item.refresh_from_db()
        self.assertEqual(item.quantite, 4)

    def test_checkout_creates_order_from_active_cart_only(self):
        historical = Cart.objects.create(user=self.user, actif=False)
        active = Cart.objects.create(user=self.user, actif=True)
        CartItem.objects.create(cart=historical, produit=self.other_product)
        active_item = CartItem.objects.create(cart=active, produit=self.product)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("shop:checkout"),
            {
                "checkout_token": str(uuid.uuid4()),
                "rue": "1 rue du Test",
                "ville": "Paris",
                "code_postal": "75001",
                "pays": "France",
                "telephone": "0102030405",
            },
        )

        self.assertEqual(response.status_code, 302)
        order = Commande.objects.get()
        self.assertEqual(order.source_cart, active)
        self.assertEqual(list(order.lignes.values_list("source_cart_item", flat=True)), [active_item.id])
