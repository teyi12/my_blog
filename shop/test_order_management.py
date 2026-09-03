from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from payments.models import Adresse
from shop.models import Commande, LigneCommande, Produit
from shop.services import finalize_paid_order


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
            fulfillment_status="TO_PREPARE",
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
        self.assertContains(response, "À préparer")

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
        self.assertContains(response, "Traitement de la commande")

    def test_non_staff_cannot_change_fulfillment(self):
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("shop:commande_traitement_modifier", args=[self.order.pk]),
            {"statut": "PREPARING"},
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, "TO_PREPARE")

    def test_staff_can_advance_paid_order_fulfillment(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("shop:commande_traitement_modifier", args=[self.order.pk]),
            {"statut": "PREPARING"},
        )
        self.assertRedirects(
            response,
            reverse("shop:commande_gestion_detail", args=[self.order.pk]),
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, "PREPARING")
        self.assertEqual(self.order.payment_status, "SUCCESS")

    def test_staff_cannot_skip_fulfillment_steps(self):
        self.client.force_login(self.staff)
        self.client.post(
            reverse("shop:commande_traitement_modifier", args=[self.order.pk]),
            {"statut": "SHIPPED"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, "TO_PREPARE")

    def test_unpaid_order_cannot_advance_fulfillment(self):
        unpaid = Commande.objects.create(
            client=self.customer,
            total=Decimal("15.00"),
            currency="EUR",
            payment_status="PENDING",
        )
        self.client.force_login(self.staff)
        self.client.post(
            reverse("shop:commande_traitement_modifier", args=[unpaid.pk]),
            {"statut": "TO_PREPARE"},
        )
        unpaid.refresh_from_db()
        self.assertEqual(unpaid.fulfillment_status, "WAITING_PAYMENT")

    def test_canceling_fulfillment_does_not_change_payment_status(self):
        self.client.force_login(self.staff)
        self.client.post(
            reverse("shop:commande_traitement_modifier", args=[self.order.pk]),
            {"statut": "CANCELED"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, "CANCELED")
        self.assertEqual(self.order.payment_status, "SUCCESS")

    def test_payment_finalization_queues_order_for_preparation(self):
        order = Commande.objects.create(
            client=self.customer,
            total=Decimal("20.00"),
            currency="EUR",
            payment_status="PROCESSING",
        )
        finalize_paid_order(order.pk)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "SUCCESS")
        self.assertEqual(order.fulfillment_status, "TO_PREPARE")

    def test_shipping_requires_carrier_and_tracking_number(self):
        self.order.fulfillment_status = "PREPARING"
        self.order.save(update_fields=["fulfillment_status"])
        self.client.force_login(self.staff)
        self.client.post(
            reverse("shop:commande_traitement_modifier", args=[self.order.pk]),
            {"statut": "SHIPPED"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, "PREPARING")
        self.assertEqual(self.order.carrier, "")
        self.assertEqual(self.order.tracking_number, "")
        self.assertIsNone(self.order.shipped_at)

    def test_shipping_saves_tracking_and_timestamp(self):
        self.order.fulfillment_status = "PREPARING"
        self.order.save(update_fields=["fulfillment_status"])
        self.client.force_login(self.staff)
        self.client.post(
            reverse("shop:commande_traitement_modifier", args=[self.order.pk]),
            {
                "statut": "SHIPPED",
                "carrier": "DHL",
                "tracking_number": "TRACK-12345",
            },
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, "SHIPPED")
        self.assertEqual(self.order.carrier, "DHL")
        self.assertEqual(self.order.tracking_number, "TRACK-12345")
        self.assertIsNotNone(self.order.shipped_at)
        self.assertEqual(self.order.payment_status, "SUCCESS")

    def test_delivery_sets_delivery_timestamp(self):
        self.order.fulfillment_status = "SHIPPED"
        self.order.carrier = "DHL"
        self.order.tracking_number = "TRACK-12345"
        self.order.save(update_fields=["fulfillment_status", "carrier", "tracking_number"])
        self.client.force_login(self.staff)
        self.client.post(
            reverse("shop:commande_traitement_modifier", args=[self.order.pk]),
            {"statut": "DELIVERED"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, "DELIVERED")
        self.assertIsNotNone(self.order.delivered_at)
        self.assertEqual(self.order.payment_status, "SUCCESS")
