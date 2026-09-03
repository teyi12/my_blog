from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from shop.models import Commande, LigneCommande, Produit


class CustomerOrderHistoryTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.customer = user_model.objects.create_user(
            email="customer-orders@example.com",
            password="test-password",
            first_name="Teyi",
            last_name="Lawson",
        )
        self.other_customer = user_model.objects.create_user(
            email="other-customer@example.com",
            password="test-password",
        )
        self.product = Produit.objects.create(
            nom="Pantalon client",
            slug="pantalon-client-orders",
            prix=Decimal("95.00"),
        )
        self.order = Commande.objects.create(
            client=self.customer,
            total=Decimal("95.00"),
            currency="EUR",
            payment_status="SUCCESS",
            payment_channel="STRIPE",
            fulfillment_status="DELIVERED",
            carrier="DHL",
            tracking_number="TEST-71-2026",
            shipped_at=timezone.now(),
            delivered_at=timezone.now(),
        )
        LigneCommande.objects.create(
            commande=self.order,
            produit=self.product,
            quantite=1,
            prix_unitaire=Decimal("95.00"),
        )
        self.other_order = Commande.objects.create(
            client=self.other_customer,
            total=Decimal("25.00"),
            currency="EUR",
            payment_status="SUCCESS",
            fulfillment_status="TO_PREPARE",
        )

    def test_order_history_requires_login(self):
        response = self.client.get(reverse("shop:mes_commandes"))
        self.assertEqual(response.status_code, 302)

    def test_customer_sees_only_own_orders(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("shop:mes_commandes"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Commande #{self.order.pk}")
        self.assertNotContains(response, f"Commande #{self.other_order.pk}")
        self.assertContains(response, "Livrée")
        self.assertContains(response, "TEST-71-2026")

    def test_customer_can_view_own_order_detail(self):
        self.client.force_login(self.customer)
        response = self.client.get(
            reverse("shop:ma_commande_detail", args=[self.order.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pantalon client")
        self.assertContains(response, "DHL")
        self.assertContains(response, "TEST-71-2026")
        self.assertContains(response, "Suivi de votre commande")

    def test_customer_cannot_view_another_customers_order(self):
        self.client.force_login(self.customer)
        response = self.client.get(
            reverse("shop:ma_commande_detail", args=[self.other_order.pk])
        )
        self.assertEqual(response.status_code, 404)
