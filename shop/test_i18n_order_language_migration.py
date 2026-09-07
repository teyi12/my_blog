from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class OrderLanguageMigrationTests(TransactionTestCase):
    migrate_from = [("shop", "0016_populate_french_product_category_translations")]
    migrate_to = [("shop", "0017_commande_language_code")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        User = old_apps.get_model("accounts", "CustomUser")
        Commande = old_apps.get_model("shop", "Commande")
        self.user = User.objects.create(email="historical-order-language@example.com")
        self.order = Commande.objects.create(
            client=self.user,
            total=Decimal("42.00"),
            payment_status="SUCCESS",
            currency="EUR",
        )

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def test_historical_orders_receive_french_without_other_data_changes(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        Commande = apps.get_model("shop", "Commande")
        order = Commande.objects.get(pk=self.order.pk)
        self.assertEqual(order.language_code, "fr")
        self.assertEqual(order.total, Decimal("42.00"))
        self.assertEqual(order.payment_status, "SUCCESS")
        self.assertEqual(order.currency, "EUR")
