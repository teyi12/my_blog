import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import translation

from shop.admin import StockMovementAdmin
from shop.inventory import (
    OrderAlreadyRestocked,
    OrderNotRestockable,
    StockUnavailable,
    adjust_product_stock,
    commit_order_stock,
    release_order_stock,
    reserve_order_stock,
    restock_refunded_order,
)
from shop.models import Commande, LigneCommande, Produit, StockMovement
from shop.services import execute_with_sqlite_lock_retry


class InventoryAuditTrailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user(
            email="inventory-staff@example.test",
            password="test-password",
            is_staff=True,
        )
        cls.customer = get_user_model().objects.create_user(
            email="inventory-customer@example.test",
            password="test-password",
        )

    def create_product(self, *, stock=5, suffix=None, digital=False):
        suffix = suffix or uuid.uuid4().hex
        return Produit.objects.create(
            nom=f"Produit {suffix}",
            slug=f"produit-{suffix}",
            prix=Decimal("10.00"),
            stock=stock,
            fichier=f"produits/fichiers/{suffix}.pdf" if digital else None,
        )

    def create_order(self, product, *, quantity=2, reserve=True):
        order = Commande.objects.create(
            client=self.customer,
            total=product.prix * quantity,
        )
        line = LigneCommande.objects.create(
            commande=order,
            produit=product,
            quantite=quantity,
            prix_unitaire=product.prix,
        )
        if reserve:
            reserve_order_stock(order.pk)
        return order, line

    def adjustment_data(self, product, *, quantity=2, reason="Livraison fournisseur"):
        return {
            "produit": product.pk,
            "quantity": quantity,
            "reason": reason,
            "idempotency_key": uuid.uuid4(),
        }

    def test_positive_and_negative_adjustments_are_audited(self):
        product = self.create_product(stock=5)
        positive = adjust_product_stock(
            product.pk, 3, "Livraison", self.staff, "manual:test-positive"
        )
        negative = adjust_product_stock(
            product.pk, -2, "Inventaire", self.staff, "manual:test-negative"
        )

        product.refresh_from_db()
        self.assertEqual(product.stock, 6)
        self.assertEqual(
            (positive.stock_before, positive.quantity, positive.stock_after),
            (5, 3, 8),
        )
        self.assertEqual(
            (negative.stock_before, negative.quantity, negative.stock_after),
            (8, -2, 6),
        )
        self.assertEqual(positive.actor, self.staff)

    def test_adjustment_form_rejects_empty_reason_and_zero(self):
        product = self.create_product()
        self.client.force_login(self.staff)
        for quantity, reason in ((1, "   "), (0, "Comptage")):
            with self.subTest(quantity=quantity, reason=reason):
                response = self.client.post(
                    reverse("shop:inventory_adjust"),
                    self.adjustment_data(product, quantity=quantity, reason=reason),
                )
                self.assertEqual(response.status_code, 400)
        product.refresh_from_db()
        self.assertEqual(product.stock, 5)
        self.assertFalse(StockMovement.objects.exists())

    def test_adjustment_mutation_is_staff_post_only_and_csrf_protected(self):
        product = self.create_product()
        url = reverse("shop:inventory_adjust")

        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 405)

        self.client.force_login(self.customer)
        response = self.client.post(url, self.adjustment_data(product))
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        self.assertEqual(product.stock, 5)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        response = csrf_client.post(url, self.adjustment_data(product))
        self.assertEqual(response.status_code, 403)

        with self.assertRaises(PermissionDenied):
            adjust_product_stock(
                product.pk, 1, "Interdit", self.customer, "manual:non-staff"
            )

    def test_negative_stock_is_rejected_by_service_and_database(self):
        product = self.create_product(stock=1)
        with self.assertRaises(StockUnavailable):
            adjust_product_stock(
                product.pk, -2, "Trop bas", self.staff, "manual:negative"
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Produit.objects.filter(pk=product.pk).update(stock=-1)
        self.assertFalse(StockMovement.objects.exists())

    def test_reservation_release_and_confirmation_are_idempotent(self):
        product = self.create_product(stock=5)
        order, line = self.create_order(product, quantity=2, reserve=False)

        reserve_order_stock(order.pk)
        reserve_order_stock(order.pk)
        self.assertEqual(
            StockMovement.objects.filter(movement_type="RESERVATION").count(), 1
        )
        release_order_stock(order.pk)
        release_order_stock(order.pk)
        self.assertEqual(
            StockMovement.objects.filter(movement_type="RELEASE").count(), 1
        )

        reserve_order_stock(order.pk)
        commit_order_stock(order.pk)
        commit_order_stock(order.pk)
        product.refresh_from_db()
        order.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(product.stock, 3)
        self.assertEqual(order.inventory_cycle, 2)
        self.assertEqual(line.stock_reserved_quantity, 2)
        self.assertEqual(
            StockMovement.objects.filter(movement_type="RESERVATION").count(), 2
        )
        self.assertEqual(
            StockMovement.objects.filter(movement_type="SALE").count(), 1
        )

    def test_refunded_order_is_restocked_explicitly_once(self):
        product = self.create_product(stock=5)
        order, _line = self.create_order(product, quantity=2)
        commit_order_stock(order.pk)
        Commande.objects.filter(pk=order.pk).update(payment_status="REFUNDED")

        restock_refunded_order(order.pk, self.staff)
        product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(product.stock, 5)
        self.assertEqual(order.inventory_status, "RESTOCKED")
        movement = StockMovement.objects.get(movement_type="RESTOCK")
        self.assertEqual((movement.stock_before, movement.quantity, movement.stock_after), (3, 2, 5))
        self.assertEqual(movement.actor, self.staff)
        with self.assertRaises(OrderAlreadyRestocked):
            restock_refunded_order(order.pk, self.staff)
        self.assertEqual(StockMovement.objects.filter(movement_type="RESTOCK").count(), 1)

    def test_restock_view_is_staff_post_only_and_csrf_protected(self):
        product = self.create_product(stock=2)
        order, _line = self.create_order(product, quantity=1)
        commit_order_stock(order.pk)
        Commande.objects.filter(pk=order.pk).update(payment_status="REFUNDED")
        url = reverse("shop:commande_remettre_en_stock", args=[order.pk])

        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        self.assertEqual(csrf_client.post(url).status_code, 403)

        self.client.force_login(self.customer)
        self.assertEqual(self.client.post(url).status_code, 302)
        product.refresh_from_db()
        self.assertEqual(product.stock, 1)

        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(url).status_code, 302)
        product.refresh_from_db()
        self.assertEqual(product.stock, 2)

    def test_historical_digital_unmanaged_and_deleted_products_are_not_restockable(self):
        historical = self.create_product(stock=3, suffix="historical")
        historical_order, historical_line = self.create_order(
            historical, quantity=1, reserve=False
        )
        Commande.objects.filter(pk=historical_order.pk).update(
            payment_status="REFUNDED", inventory_status="COMMITTED"
        )
        LigneCommande.objects.filter(pk=historical_line.pk).update(
            stock_reserved_quantity=1
        )

        digital = self.create_product(stock=0, suffix="digital", digital=True)
        digital_order, digital_line = self.create_order(
            digital, quantity=1, reserve=False
        )
        Commande.objects.filter(pk=digital_order.pk).update(
            payment_status="REFUNDED", inventory_status="COMMITTED"
        )
        LigneCommande.objects.filter(pk=digital_line.pk).update(
            stock_reserved_quantity=1
        )

        unmanaged = self.create_product(stock=None, suffix="unmanaged")
        unmanaged_order, unmanaged_line = self.create_order(
            unmanaged, quantity=1, reserve=False
        )
        Commande.objects.filter(pk=unmanaged_order.pk).update(
            payment_status="REFUNDED", inventory_status="COMMITTED"
        )
        LigneCommande.objects.filter(pk=unmanaged_line.pk).update(
            stock_reserved_quantity=1
        )

        deleted = self.create_product(stock=2, suffix="deleted")
        deleted_order, deleted_line = self.create_order(
            deleted, quantity=1, reserve=False
        )
        Commande.objects.filter(pk=deleted_order.pk).update(
            payment_status="REFUNDED", inventory_status="COMMITTED"
        )
        LigneCommande.objects.filter(pk=deleted_line.pk).update(
            stock_reserved_quantity=1
        )
        deleted.delete()

        for order in (
            historical_order,
            digital_order,
            unmanaged_order,
            deleted_order,
        ):
            with self.subTest(order=order.pk), self.assertRaises(OrderNotRestockable):
                restock_refunded_order(order.pk, self.staff)
        self.assertFalse(StockMovement.objects.filter(movement_type="RESTOCK").exists())

    def test_movement_balance_and_application_immutability(self):
        product = self.create_product()
        movement = adjust_product_stock(
            product.pk, 1, "Comptage", self.staff, "manual:immutable"
        )
        movement.reason = "Altéré"
        with self.assertRaises(ValidationError):
            movement.save()
        with self.assertRaises(ValidationError):
            movement.delete()
        with self.assertRaises(ValidationError):
            StockMovement.objects.filter(pk=movement.pk).update(reason="Altéré")
        with self.assertRaises(ValidationError):
            StockMovement.objects.filter(pk=movement.pk).delete()
        with self.assertRaises(ValidationError):
            StockMovement.objects.bulk_update([movement], ["reason"])

        with self.assertRaises(IntegrityError), transaction.atomic():
            StockMovement.objects.create(
                produit=product,
                product_id_snapshot=product.pk,
                product_name_snapshot=product.nom,
                movement_type="MANUAL",
                quantity=1,
                stock_before=5,
                stock_after=9,
                reason="Incohérent",
                idempotency_key="manual:unbalanced",
            )

    def test_admin_is_read_only_and_stock_is_not_editable(self):
        product = self.create_product()
        movement = adjust_product_stock(
            product.pk, 1, "Comptage", self.staff, "manual:admin-readonly"
        )
        superuser = get_user_model().objects.create_superuser(
            email="inventory-admin@example.test", password="test-password"
        )
        request = type("Request", (), {"user": superuser})()
        movement_admin = StockMovementAdmin(StockMovement, admin.site)
        self.assertFalse(movement_admin.has_add_permission(request))
        self.assertFalse(movement_admin.has_change_permission(request, movement))
        self.assertFalse(movement_admin.has_delete_permission(request, movement))

        self.client.force_login(superuser)
        change = self.client.get(reverse("admin:shop_produit_change", args=[product.pk]))
        self.assertNotContains(change, 'name="stock"')

        movement_change_url = reverse(
            "admin:shop_stockmovement_change", args=[movement.pk]
        )
        response = self.client.post(
            movement_change_url,
            {"reason": "Tentative de modification"},
        )
        self.assertEqual(response.status_code, 403)
        movement.refresh_from_db()
        self.assertEqual(movement.reason, "Comptage")
        self.assertEqual(
            self.client.get(reverse("admin:shop_stockmovement_add")).status_code,
            403,
        )

    def test_staff_dashboard_shows_out_of_stock_and_threshold_alerts(self):
        empty = self.create_product(stock=0, suffix="empty")
        low = self.create_product(stock=2, suffix="low")
        Produit.objects.filter(pk=low.pk).update(low_stock_threshold=3)
        healthy = self.create_product(stock=8, suffix="healthy")
        Produit.objects.filter(pk=healthy.pk).update(low_stock_threshold=3)
        self.client.force_login(self.staff)
        response = self.client.get(reverse("shop:inventory_gestion"))
        alerts = list(response.context["inventory_alerts"])
        self.assertIn(empty, alerts)
        self.assertIn(low, alerts)
        self.assertNotIn(healthy, alerts)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Produit.objects.filter(pk=healthy.pk).update(low_stock_threshold=-1)

    def test_inventory_interface_is_translated_in_english_and_german(self):
        self.client.force_login(self.staff)
        for language_code, expected in (
            ("en", "Inventory management"),
            ("de", "Bestandsverwaltung"),
        ):
            with self.subTest(language=language_code), translation.override(
                language_code
            ):
                response = self.client.get(reverse("shop:inventory_gestion"))
                self.assertContains(response, expected)


class ConcurrentAdjustmentAndReservationTests(TransactionTestCase):
    reset_sequences = True

    def test_adjustment_and_reservation_cannot_both_consume_last_item(self):
        staff = get_user_model().objects.create_user(
            email="concurrent-stock-staff@example.test", is_staff=True
        )
        customer = get_user_model().objects.create_user(
            email="concurrent-stock-customer@example.test"
        )
        product = Produit.objects.create(
            nom="Dernier produit audité",
            slug="dernier-produit-audite",
            prix=Decimal("10.00"),
            stock=1,
        )
        order = Commande.objects.create(client=customer, total=product.prix)
        LigneCommande.objects.create(
            commande=order,
            produit=product,
            quantite=1,
            prix_unitaire=product.prix,
        )
        barrier = Barrier(2)

        def reserve():
            close_old_connections()
            barrier.wait()
            try:
                execute_with_sqlite_lock_retry(
                    lambda: reserve_order_stock(order.pk),
                    attempts=10,
                    base_delay=0.01,
                )
            except StockUnavailable:
                result = "unavailable"
            else:
                result = "reserved"
            close_old_connections()
            return result

        def adjust():
            close_old_connections()
            barrier.wait()
            try:
                execute_with_sqlite_lock_retry(
                    lambda: adjust_product_stock(
                        product.pk,
                        -1,
                        "Comptage concurrent",
                        staff,
                        "manual:concurrent",
                    ),
                    attempts=10,
                    base_delay=0.01,
                )
            except StockUnavailable:
                result = "unavailable"
            else:
                result = "adjusted"
            close_old_connections()
            return result

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [executor.submit(reserve), executor.submit(adjust)]
            outcomes = [future.result() for future in results]

        self.assertEqual(outcomes.count("unavailable"), 1)
        self.assertEqual(Produit.objects.get(pk=product.pk).stock, 0)
        self.assertEqual(
            StockMovement.objects.filter(quantity=-1).count(),
            1,
        )
