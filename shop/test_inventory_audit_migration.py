from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class InventoryAuditMigrationTests(TransactionTestCase):
    migrate_from = [("shop", "0021_inventory_integrity")]
    migrate_to = [("shop", "0022_inventory_audit_trail")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        apps = executor.loader.project_state(self.migrate_from).apps
        User = apps.get_model("accounts", "CustomUser")
        Commande = apps.get_model("shop", "Commande")
        LigneCommande = apps.get_model("shop", "LigneCommande")
        Produit = apps.get_model("shop", "Produit")

        user = User.objects.create(email="audit-migration@example.test")
        self.managed_id = Produit.objects.create(
            nom="Produit physique géré",
            slug="produit-physique-gere",
            prix=Decimal("10.00"),
            stock=7,
        ).pk
        self.zero_id = Produit.objects.create(
            nom="Produit épuisé",
            slug="produit-epuise",
            prix=Decimal("10.00"),
            stock=0,
        ).pk
        self.unmanaged_id = Produit.objects.create(
            nom="Produit non géré",
            slug="produit-non-gere",
            prix=Decimal("10.00"),
            stock=None,
        ).pk
        self.digital_id = Produit.objects.create(
            nom="Produit numérique",
            slug="produit-numerique",
            prix=Decimal("10.00"),
            stock=4,
            fichier="produits/fichiers/numerique.pdf",
        ).pk
        paid_order = Commande.objects.create(
            client=user,
            total=Decimal("10.00"),
            payment_status="SUCCESS",
            inventory_status="COMMITTED",
        )
        LigneCommande.objects.create(
            commande=paid_order,
            produit_id=self.managed_id,
            quantite=1,
            prix_unitaire=Decimal("10.00"),
            stock_reserved_quantity=0,
        )
        self.paid_order_id = paid_order.pk

    def tearDown(self):
        MigrationExecutor(connection).migrate(
            MigrationExecutor(connection).loader.graph.leaf_nodes()
        )
        super().tearDown()

    def test_initial_movements_snapshot_only_current_managed_stock(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        Produit = apps.get_model("shop", "Produit")
        StockMovement = apps.get_model("shop", "StockMovement")

        self.assertEqual(
            set(
                StockMovement.objects.values_list(
                    "product_id_snapshot", flat=True
                )
            ),
            {self.managed_id, self.zero_id},
        )
        movement = StockMovement.objects.get(
            product_id_snapshot=self.managed_id
        )
        self.assertEqual(
            (movement.stock_before, movement.quantity, movement.stock_after),
            (0, 7, 7),
        )
        self.assertEqual(Produit.objects.get(pk=self.managed_id).stock, 7)
        self.assertFalse(
            StockMovement.objects.filter(commande_id=self.paid_order_id).exists()
        )
