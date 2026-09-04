from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class PreActifAuditCommandTests(TransactionTestCase):
    migrate_from = [("shop", "0011_commande_shipping_tracking")]
    migrate_to = [("shop", "0014_cart_integrity_constraints")]

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.migrate_from)
        apps = self.executor.loader.project_state(self.migrate_from).apps
        User = apps.get_model("accounts", "CustomUser")
        Produit = apps.get_model("shop", "Produit")
        Cart = apps.get_model("shop", "Cart")
        CartItem = apps.get_model("shop", "CartItem")
        self.user = User.objects.create(email="pre-actif@example.com")
        product = Produit.objects.create(
            nom="Produit pré-migration",
            slug="produit-pre-migration",
            prix=Decimal("10.00"),
        )
        self.first_cart = Cart.objects.create(user=self.user)
        self.second_cart = Cart.objects.create(user=self.user)
        Cart.objects.create(user=None)
        CartItem.objects.create(
            cart=self.first_cart,
            produit=product,
            quantite=2,
            prix_unitaire=Decimal("10.00"),
        )
        CartItem.objects.create(
            cart=self.first_cart,
            produit=product,
            quantite=3,
            prix_unitaire=Decimal("10.00"),
        )

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def test_audit_works_without_the_actif_column(self):
        statements = []

        def collect_sql(execute, sql, params, many, context):
            statements.append(sql)
            return execute(sql, params, many, context)

        output = StringIO()
        with connection.execute_wrapper(collect_sql):
            call_command("audit_cart_integrity", stdout=output)

        report = output.getvalue()
        self.assertIn("Schéma pré-migration : colonne Cart.actif absente", report)
        self.assertIn("Nombre total de paniers : 3", report)
        self.assertIn("Utilisateurs possédant plusieurs paniers : 1", report)
        self.assertIn("Couples (cart, produit) dupliqués : 1", report)
        self.assertIn("quantité_fusionnée=5", report)
        self.assertIn(
            "Utilisateurs possédant plusieurs paniers actifs : ignoré",
            report,
        )
        self.assertNotIn("actif", " ".join(str(sql) for sql in statements).lower())


class CartIntegrityMigrationTests(TransactionTestCase):
    migrate_from = [("shop", "0012_cart_actif")]
    migrate_to = [("shop", "0014_cart_integrity_constraints")]

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.migrate_from)
        self.old_apps = self.executor.loader.project_state(self.migrate_from).apps
        self._seed_duplicates()

    def tearDown(self):
        executor = MigrationExecutor(connection)
        try:
            executor.migrate(self.migrate_to)
        except RuntimeError:
            CartItem = self.old_apps.get_model("shop", "CartItem")
            duplicate = CartItem.objects.order_by("id").last()
            if duplicate is not None:
                duplicate.delete()
            MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def _seed_duplicates(self):
        User = self.old_apps.get_model("accounts", "CustomUser")
        Produit = self.old_apps.get_model("shop", "Produit")
        Cart = self.old_apps.get_model("shop", "Cart")
        CartItem = self.old_apps.get_model("shop", "CartItem")
        Commande = self.old_apps.get_model("shop", "Commande")
        LigneCommande = self.old_apps.get_model("shop", "LigneCommande")

        self.user = User.objects.create(email="migration@example.com")
        self.product = Produit.objects.create(
            nom="Produit migration",
            slug="produit-migration",
            prix=Decimal("10.00"),
        )
        self.canonical_cart = Cart.objects.create(user=self.user, actif=True)
        self.historical_cart = Cart.objects.create(user=self.user, actif=True)
        self.first_item = CartItem.objects.create(
            cart=self.canonical_cart,
            produit=self.product,
            quantite=2,
            prix_unitaire=Decimal("10.00"),
        )
        self.second_item = CartItem.objects.create(
            cart=self.canonical_cart,
            produit=self.product,
            quantite=3,
            prix_unitaire=Decimal("10.00"),
        )
        self.order = Commande.objects.create(
            client=self.user,
            source_cart=self.historical_cart,
            payment_status="PENDING",
        )
        self.line = LigneCommande.objects.create(
            commande=self.order,
            produit=self.product,
            source_cart_item=self.second_item,
            quantite=3,
            prix_unitaire=Decimal("10.00"),
        )

    def test_audit_detects_then_migration_normalizes_and_preserves_history(self):
        output = StringIO()
        call_command("audit_cart_integrity", stdout=output)
        self.assertIn("Couples (cart, produit) dupliqués : 1", output.getvalue())
        self.assertIn("quantité_fusionnée=5", output.getvalue())

        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.migrate_to)
        apps = self.executor.loader.project_state(self.migrate_to).apps
        Cart = apps.get_model("shop", "Cart")
        CartItem = apps.get_model("shop", "CartItem")
        Commande = apps.get_model("shop", "Commande")
        LigneCommande = apps.get_model("shop", "LigneCommande")

        self.assertTrue(Cart.objects.get(pk=self.canonical_cart.pk).actif)
        self.assertFalse(Cart.objects.get(pk=self.historical_cart.pk).actif)
        self.assertEqual(
            Commande.objects.get(pk=self.order.pk).source_cart_id,
            self.historical_cart.pk,
        )
        items = CartItem.objects.filter(
            cart_id=self.canonical_cart.pk,
            produit_id=self.product.pk,
        )
        self.assertEqual(items.count(), 1)
        canonical_item = items.get()
        self.assertEqual(canonical_item.pk, self.first_item.pk)
        self.assertEqual(canonical_item.quantite, 5)
        self.assertEqual(
            LigneCommande.objects.get(pk=self.line.pk).source_cart_item_id,
            canonical_item.pk,
        )

    def test_migration_refuses_divergent_non_null_prices(self):
        CartItem = self.old_apps.get_model("shop", "CartItem")
        CartItem.objects.filter(pk=self.second_item.pk).update(
            prix_unitaire=Decimal("12.00")
        )

        with self.assertRaisesRegex(RuntimeError, "prix unitaires divergents"):
            MigrationExecutor(connection).migrate(self.migrate_to)

        self.assertEqual(CartItem.objects.count(), 2)
        self.assertEqual(
            list(
                CartItem.objects.order_by("id").values_list("quantite", flat=True)
            ),
            [2, 3],
        )
