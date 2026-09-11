from decimal import Decimal
from unittest.mock import patch

from django.core.files.storage import FileSystemStorage
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class OrderLineSnapshotMigrationTests(TransactionTestCase):
    migrate_from = [("shop", "0017_commande_language_code")]
    migrate_to = [("shop", "0018_order_line_snapshots")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        User = old_apps.get_model("accounts", "CustomUser")
        Produit = old_apps.get_model("shop", "Produit")
        Commande = old_apps.get_model("shop", "Commande")
        LigneCommande = old_apps.get_model("shop", "LigneCommande")

        user = User.objects.create(email="snapshot-migration@example.com")
        digital_product = Produit.objects.create(
            nom="Produit numérique historique",
            slug="produit-numerique-historique",
            prix=Decimal("11.00"),
            fichier="produits/fichiers/prive/archive.pdf",
        )
        physical_product = Produit.objects.create(
            nom="Produit physique historique",
            slug="produit-physique-historique",
            prix=Decimal("7.00"),
            fichier="",
        )
        order = Commande.objects.create(
            client=user,
            total=Decimal("18.00"),
            payment_status="SUCCESS",
        )
        self.digital_line = LigneCommande.objects.create(
            commande=order,
            produit=digital_product,
            quantite=1,
            prix_unitaire=Decimal("11.00"),
        )
        self.physical_line = LigneCommande.objects.create(
            commande=order,
            produit=physical_product,
            quantite=1,
            prix_unitaire=Decimal("7.00"),
        )

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def _migrate_forward(self):
        executor = MigrationExecutor(connection)
        with patch.object(FileSystemStorage, "open") as storage_open:
            executor.migrate(self.migrate_to)
        self.assertFalse(storage_open.called)
        return executor.loader.project_state(self.migrate_to).apps

    def test_backfill_copies_names_without_opening_files(self):
        apps = self._migrate_forward()
        LigneCommande = apps.get_model("shop", "LigneCommande")

        digital_line = LigneCommande.objects.get(pk=self.digital_line.pk)
        self.assertEqual(
            digital_line.nom_produit_snapshot,
            "Produit numérique historique",
        )
        self.assertEqual(
            digital_line.fichier_nom_stockage_snapshot,
            "produits/fichiers/prive/archive.pdf",
        )
        self.assertEqual(
            digital_line.fichier_nom_telechargement_snapshot,
            "archive.pdf",
        )
        physical_line = LigneCommande.objects.get(pk=self.physical_line.pk)
        self.assertEqual(
            physical_line.nom_produit_snapshot,
            "Produit physique historique",
        )
        self.assertEqual(physical_line.fichier_nom_stockage_snapshot, "")
        self.assertEqual(physical_line.fichier_nom_telechargement_snapshot, "")

    def test_migration_is_reversible_while_products_still_exist(self):
        self._migrate_forward()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        LigneCommande = old_apps.get_model("shop", "LigneCommande")

        self.assertTrue(
            LigneCommande.objects.filter(pk=self.digital_line.pk).exists()
        )
        self.assertTrue(
            LigneCommande.objects.filter(pk=self.physical_line.pk).exists()
        )
