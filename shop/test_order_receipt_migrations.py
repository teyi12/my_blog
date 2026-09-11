from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from django.utils import translation

from payments.models import Adresse


@override_settings(
    ORDER_RECEIPT_ISSUER_NAME="Historical Teyilawson",
    ORDER_RECEIPT_ISSUER_CONTACT="historical@example.test",
)
class OrderReceiptMigrationTests(TransactionTestCase):
    migrate_from = [("shop", "0018_order_line_snapshots")]
    migrate_to = [("shop", "0019_order_receipts")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        User = old_apps.get_model("accounts", "CustomUser")
        Commande = old_apps.get_model("shop", "Commande")
        LigneCommande = old_apps.get_model("shop", "LigneCommande")
        Produit = old_apps.get_model("shop", "Produit")

        user = User.objects.create(
            email="receipt-migration@example.test",
            first_name="Anaïs",
            last_name="Groß",
        )
        address = Adresse.objects.create(
            utilisateur_id=user.pk,
            type_adresse="LIVRAISON",
            rue="9 rue historique",
            code_postal="67000",
            ville="Straßburg",
            pays="France",
        )
        product = Produit.objects.create(
            nom_fr="Produit actuel ignoré",
            slug="receipt-migration-product",
            prix=Decimal("7.25"),
        )
        self.paid_orders = {}
        for language_code in ("fr", "de", "en"):
            order = Commande.objects.create(
                client=user,
                adresse_id=address.pk,
                total=Decimal("14.50"),
                payment_status="SUCCESS",
                payment_channel="STRIPE",
                currency="EUR",
                language_code=language_code,
            )
            LigneCommande.objects.create(
                commande=order,
                produit=product,
                quantite=2,
                prix_unitaire=Decimal("7.25"),
                nom_produit_snapshot=f"Historical {language_code} snapshot",
                fichier_nom_stockage_snapshot="private/never-open.pdf",
                fichier_nom_telechargement_snapshot="never-open.pdf",
            )
            self.paid_orders[language_code] = (order.pk, order.date_commande)

        pending = Commande.objects.create(
            client=user,
            adresse_id=address.pk,
            total=Decimal("7.25"),
            payment_status="PENDING",
            currency="EUR",
            language_code="fr",
        )
        LigneCommande.objects.create(
            commande=pending,
            produit=product,
            quantite=1,
            prix_unitaire=Decimal("7.25"),
            nom_produit_snapshot="Pending snapshot",
        )
        self.pending_order_pk = pending.pk

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def test_backfill_creates_only_paid_receipts_from_historical_snapshots(self):
        executor = MigrationExecutor(connection)
        with translation.override("de"):
            executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        OrderReceipt = apps.get_model("shop", "OrderReceipt")

        self.assertEqual(OrderReceipt.objects.count(), 3)
        self.assertFalse(
            OrderReceipt.objects.filter(commande_id=self.pending_order_pk).exists()
        )
        for language_code, (order_pk, order_date) in self.paid_orders.items():
            with self.subTest(language_code=language_code):
                receipt = OrderReceipt.objects.get(commande_id=order_pk)
                self.assertEqual(receipt.language_code, language_code)
                self.assertEqual(receipt.issued_at, order_date)
                self.assertEqual(receipt.issuer_name, "Historical Teyilawson")
                self.assertEqual(
                    receipt.issuer_contact,
                    "historical@example.test",
                )
                self.assertEqual(receipt.customer_name, "Anaïs Groß")
                self.assertEqual(receipt.address_snapshot["city"], "Straßburg")
                self.assertEqual(
                    receipt.items_snapshot,
                    [
                        {
                            "name": f"Historical {language_code} snapshot",
                            "quantity": 2,
                            "unit_price": "7.25",
                            "subtotal": "14.50",
                        }
                    ],
                )
                serialized = str(receipt.items_snapshot)
                self.assertNotIn("never-open", serialized)
                self.assertNotIn("fichier", serialized)
