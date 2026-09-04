from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from shop.management.commands.audit_cart_integrity import read_only_transaction
from shop.models import Cart, CartItem, Commande, LigneCommande, Produit


class AuditCartIntegrityCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="audit@example.com",
            password="test-password",
        )
        cls.product = Produit.objects.create(
            nom="Produit audité",
            slug="produit-audite",
            prix=Decimal("10.00"),
        )
        cls.first_cart = Cart.objects.create(user=cls.user)
        cls.second_cart = Cart.objects.create(user=cls.user, actif=False)
        cls.anonymous_cart = Cart.objects.create(user=None)
        cls.first_item = CartItem.objects.create(
            cart=cls.first_cart,
            produit=cls.product,
            quantite=2,
            prix_unitaire=Decimal("10.00"),
        )
        cls.first_order = Commande.objects.create(
            client=cls.user,
            source_cart=cls.first_cart,
            payment_status="PENDING",
        )
        cls.second_order = Commande.objects.create(
            client=cls.user,
            source_cart=cls.second_cart,
            payment_status="PENDING",
        )
        LigneCommande.objects.create(
            commande=cls.first_order,
            produit=cls.product,
            source_cart_item=cls.first_item,
            quantite=2,
            prix_unitaire=Decimal("10.00"),
        )
        LigneCommande.objects.create(
            commande=cls.second_order,
            produit=cls.product,
            source_cart_item=cls.first_item,
            quantite=3,
            prix_unitaire=Decimal("12.00"),
        )

    def test_command_reports_duplicates_prices_and_historical_relations(self):
        output = StringIO()

        call_command("audit_cart_integrity", stdout=output)

        report = output.getvalue()
        self.assertIn("Nombre total de paniers : 3", report)
        self.assertIn("Paniers authentifiés : 2", report)
        self.assertIn("Paniers anonymes : 1", report)
        self.assertIn("Utilisateurs possédant plusieurs paniers : 1", report)
        self.assertIn("Nombre maximal de paniers pour un utilisateur : 2", report)
        self.assertIn("Paniers référencés par une commande : 2", report)
        self.assertIn("commandes en attente : 2", report)
        self.assertIn("Nombre total de lignes de panier : 1", report)
        self.assertIn("Couples (cart, produit) dupliqués : 0", report)
        self.assertIn(
            "Groupes dupliqués ayant plusieurs prix unitaires distincts : 0",
            report,
        )
        self.assertIn("Lignes de panier référencées par LigneCommande : 1", report)
        self.assertIn(
            "Doublons dont plusieurs lignes sont référencées historiquement : 0",
            report,
        )
        self.assertIn(
            "Commandes non finalisées utilisant un panier source : 2",
            report,
        )

    def test_command_does_not_create_update_or_delete_rows(self):
        before = {
            "carts": list(Cart.objects.order_by("id").values()),
            "items": list(CartItem.objects.order_by("id").values()),
            "orders": list(Commande.objects.order_by("id").values()),
            "lines": list(LigneCommande.objects.order_by("id").values()),
        }

        call_command("audit_cart_integrity", stdout=StringIO())

        after = {
            "carts": list(Cart.objects.order_by("id").values()),
            "items": list(CartItem.objects.order_by("id").values()),
            "orders": list(Commande.objects.order_by("id").values()),
            "lines": list(LigneCommande.objects.order_by("id").values()),
        }
        self.assertEqual(after, before)

    def test_postgresql_enables_read_only_transaction(self):
        mocked_connection = MagicMock(vendor="postgresql")
        mocked_cursor = mocked_connection.cursor.return_value.__enter__.return_value
        mocked_atomic = MagicMock()

        with patch(
            "shop.management.commands.audit_cart_integrity.connection",
            mocked_connection,
        ), patch(
            "shop.management.commands.audit_cart_integrity.transaction.atomic",
            return_value=mocked_atomic,
        ):
            with read_only_transaction():
                pass

        mocked_atomic.__enter__.assert_called_once_with()
        mocked_atomic.__exit__.assert_called_once()
        mocked_cursor.execute.assert_called_once_with("SET TRANSACTION READ ONLY")


class EmptyAuditCartIntegrityCommandTests(TestCase):
    def test_empty_database_reports_zero_as_maximum(self):
        output = StringIO()

        call_command("audit_cart_integrity", stdout=output)

        self.assertIn(
            "Nombre maximal de paniers pour un utilisateur : 0",
            output.getvalue(),
        )
