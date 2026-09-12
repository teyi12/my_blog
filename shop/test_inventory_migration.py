from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class InventoryMigrationTests(TransactionTestCase):
    migrate_from = [("shop", "0020_alter_commande_payment_status")]
    migrate_to = [("shop", "0021_inventory_integrity")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        User = old_apps.get_model("accounts", "CustomUser")
        Commande = old_apps.get_model("shop", "Commande")
        Produit = old_apps.get_model("shop", "Produit")

        user = User.objects.create(email="inventory-migration@example.test")
        self.product_id = Produit.objects.create(
            nom="Produit historique",
            slug="produit-stock-historique",
            prix=Decimal("10.00"),
        ).pk
        self.paid_id = Commande.objects.create(
            client=user,
            total=Decimal("10.00"),
            payment_status="SUCCESS",
            cart_finalized_at=timezone.now(),
        ).pk
        self.refunded_id = Commande.objects.create(
            client=user,
            total=Decimal("10.00"),
            payment_status="REFUNDED",
        ).pk
        self.pending_id = Commande.objects.create(
            client=user,
            total=Decimal("10.00"),
            payment_status="PENDING",
        ).pk

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_backfill_preserves_products_and_marks_only_historical_sales(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        Commande = apps.get_model("shop", "Commande")
        Produit = apps.get_model("shop", "Produit")

        self.assertIsNone(Produit.objects.get(pk=self.product_id).stock)
        self.assertEqual(
            Commande.objects.get(pk=self.paid_id).inventory_status,
            "COMMITTED",
        )
        self.assertEqual(
            Commande.objects.get(pk=self.refunded_id).inventory_status,
            "COMMITTED",
        )
        self.assertEqual(
            Commande.objects.get(pk=self.pending_id).inventory_status,
            "NONE",
        )
