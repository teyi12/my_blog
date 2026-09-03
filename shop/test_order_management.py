from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from payments.models import Adresse
from shop.models import Commande, LigneCommande, Produit


class OrderManagementTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            email="staff-orders@example.com",
            password="test-password",
            is_staff=True,
        )
        self.customer = user_model.objects.create_user(
            email="client@example.com",
            password="test-password",
            first_name="Marie",
            last_name="Martin",
        )
        self.address = Adresse.objects.create(
            utilisateur=self.customer,
            rue="10 rue du Test",
            ville="Lahr",
            code_postal="77933",
            pays="Allemagne",
        )
        self.product = Produit.objects.create(
            nom="Produit test",
            slug="produit-test-commandes",
            prix=Decimal("25.00"),
        )
        self.order = Commande.objects.create(
            client=self.customer,
            adresse=self.address,
            total=Decimal("50.00"),
            currency="EUR",
            payment_status="SUCCESS",
            payment_channel="STRIPE",
            transaction_id="tx_test_123",
        )
        LigneCommande.objects.create(
            commande=self.order,
            produit=self.product,
            quantite=2,
            prix_unitaire=Decimal("25.00"),
        )

    def test_order_management_requires_staff(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("shop:commande_gestion_liste"))
        self.assertEqual(response.status_code, 302)

    def test_staff_can_list_orders(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("shop:commande_gestion_liste"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"#{self.order.pk}")
        self.assertContains(response, "client@example.com")
        self.assertContains(response, "Payée")

    def test_staff_can_filter_orders_by_status(self):
        Commande.objects.create(
            client=self.customer,
            total=Decimal("10.00"),
            currency="EUR",
            payment_status="PENDING",
        )
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("shop:commande_gestion_liste"),
            {"statut": "SUCCESS"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["commandes"]), [self.order])

    def test_staff_can_search_order_by_customer_email(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("shop:commande_gestion_liste"),
            {"q": "client@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"#{self.order.pk}")

    def test_staff_can_view_order_detail(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("shop:commande_gestion_detail", args=[self.order.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Produit test")
        self.assertContains(response, "10 rue du Test")
        self.assertContains(response, "tx_test_123")
