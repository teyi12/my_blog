from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from shop.models import Cart, CartItem, Commande, Produit


class FixCartsCommandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="maintenance-carts@example.com",
            password="test-password",
        )
        self.product = Produit.objects.create(
            nom="Produit maintenance",
            slug="produit-maintenance",
            prix=Decimal("12.50"),
        )
        self.zero_price_product = Produit.objects.create(
            nom="Produit gratuit maintenance",
            slug="produit-gratuit-maintenance",
            prix=Decimal("0.00"),
        )
        self.cart = Cart.objects.create(user=self.user)
        self.missing_price = CartItem.objects.create(
            cart=self.cart,
            produit=self.product,
            quantite=1,
        )
        CartItem.objects.filter(pk=self.missing_price.pk).update(prix_unitaire=None)
        self.zero_price = CartItem.objects.create(
            cart=self.cart,
            produit=self.zero_price_product,
            quantite=1,
            prix_unitaire=Decimal("0.00"),
        )
        CartItem.objects.filter(pk=self.zero_price.pk).update(
            prix_unitaire=Decimal("0.00")
        )

    def test_dry_run_reports_without_writing(self):
        output = StringIO()
        call_command("fix_carts", dry_run=True, stdout=output)

        self.missing_price.refresh_from_db()
        self.zero_price.refresh_from_db()
        self.assertIsNone(self.missing_price.prix_unitaire)
        self.assertEqual(self.zero_price.prix_unitaire, Decimal("0.00"))
        self.assertIn("1 ligne(s) CartItem seraient modifiées", output.getvalue())

    def test_real_execution_updates_only_missing_prices(self):
        output = StringIO()
        call_command("fix_carts", stdout=output)

        self.missing_price.refresh_from_db()
        self.zero_price.refresh_from_db()
        self.assertEqual(self.missing_price.prix_unitaire, self.product.prix)
        self.assertEqual(self.zero_price.prix_unitaire, Decimal("0.00"))
        self.assertIn("1 ligne(s) CartItem modifiées", output.getvalue())


class FixCommandesCommandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="maintenance-orders@example.com",
            password="test-password",
        )
        self.blank_currency = Commande.objects.create(
            client=self.user,
            payment_status="PENDING",
            currency="EUR",
        )
        Commande.objects.filter(pk=self.blank_currency.pk).update(currency="")
        self.invalid_status = Commande.objects.create(
            client=self.user,
            payment_status="UNKNOWN",
        )
        self.processing = Commande.objects.create(
            client=self.user,
            payment_status="PROCESSING",
        )
        self.success = Commande.objects.create(
            client=self.user,
            payment_status="SUCCESS",
        )
        Commande.objects.filter(pk=self.success.pk).update(currency="")

    def test_dry_run_reports_without_writing(self):
        output = StringIO()
        call_command("fix_commandes", dry_run=True, stdout=output)

        self.blank_currency.refresh_from_db()
        self.invalid_status.refresh_from_db()
        self.processing.refresh_from_db()
        self.success.refresh_from_db()
        self.assertEqual(self.blank_currency.currency, "")
        self.assertEqual(self.invalid_status.payment_status, "UNKNOWN")
        self.assertEqual(self.processing.payment_status, "PROCESSING")
        self.assertEqual(self.success.payment_status, "SUCCESS")
        self.assertEqual(self.success.currency, "")
        self.assertIn("2 ligne(s) Commande seraient modifiées", output.getvalue())

    def test_real_execution_preserves_payment_states(self):
        output = StringIO()
        call_command("fix_commandes", stdout=output)

        self.blank_currency.refresh_from_db()
        self.invalid_status.refresh_from_db()
        self.processing.refresh_from_db()
        self.success.refresh_from_db()
        self.assertEqual(self.blank_currency.currency, "EUR")
        self.assertEqual(self.invalid_status.payment_status, "PENDING")
        self.assertEqual(self.processing.payment_status, "PROCESSING")
        self.assertEqual(self.success.payment_status, "SUCCESS")
        self.assertEqual(self.success.currency, "")
        self.assertIn("2 ligne(s) Commande modifiées", output.getvalue())
