from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import stripe
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from payments.models import Adresse, Payment
from shop.models import Cart, CartItem, Commande, LigneCommande, OrderReceipt, Produit


RETRIEVE = (
    "payments.management.commands.reconcile_stripe_payments."
    "stripe.checkout.Session.retrieve"
)


class ReconcileStripePaymentsCommandTests(TestCase):
    def setUp(self):
        self.bundle_counter = 0
        self.user, self.order, self.payment, self.cart_item = self.create_bundle()

    def create_bundle(self, *, age_minutes=61, session_id=None):
        self.bundle_counter += 1
        suffix = self.bundle_counter
        user = get_user_model().objects.create_user(
            email=f"reconciliation-{suffix}@example.test",
            password="test-password",
        )
        product = Produit.objects.create(
            nom=f"Produit réconciliation {suffix}",
            slug=f"produit-reconciliation-{suffix}",
            prix=Decimal("20.00"),
        )
        cart = Cart.objects.create(user=user)
        cart_item = CartItem.objects.create(
            cart=cart,
            produit=product,
            quantite=1,
            prix_unitaire=product.prix,
        )
        address = Adresse.objects.create(
            utilisateur=user,
            rue="1 rue des Tests",
            ville="Paris",
            code_postal="75001",
            pays="France",
        )
        session_id = session_id or f"cs_reconciliation_{suffix}"
        order = Commande.objects.create(
            client=user,
            adresse=address,
            source_cart=cart,
            total=Decimal("20.00"),
            currency="EUR",
            transaction_id=session_id,
            payment_channel="STRIPE",
            payment_status="PROCESSING",
        )
        LigneCommande.objects.create(
            commande=order,
            produit=product,
            source_cart_item=cart_item,
            quantite=1,
            prix_unitaire=product.prix,
        )
        payment = Payment.objects.create(
            commande=order,
            montant=order.total,
            devise=order.currency,
            transaction_id=session_id,
            channel="STRIPE",
            status="PROCESSING",
        )
        Payment.objects.filter(pk=payment.pk).update(
            updated_at=timezone.now() - timedelta(minutes=age_minutes)
        )
        payment.refresh_from_db()
        return user, order, payment, cart_item

    def stripe_session(self, payment=None, **overrides):
        payment = payment or self.payment
        session = {
            "id": payment.transaction_id,
            "payment_status": "paid",
            "status": "complete",
            "amount_total": 2000,
            "currency": "eur",
            "metadata": {
                "commande_id": str(payment.commande_id),
                "payment_id": str(payment.id),
                "user_id": str(payment.commande.client_id),
            },
        }
        session.update(overrides)
        return session

    def run_command(self, **options):
        stdout = StringIO()
        stderr = StringIO()
        call_command(
            "reconcile_stripe_payments",
            stdout=stdout,
            stderr=stderr,
            **options,
        )
        return stdout.getvalue(), stderr.getvalue()

    def assert_payment_unchanged(self, payment=None):
        payment = payment or self.payment
        payment.refresh_from_db()
        payment.commande.refresh_from_db()
        self.assertEqual(payment.status, "PROCESSING")
        self.assertEqual(payment.commande.payment_status, "PROCESSING")
        self.assertIsNone(payment.commande.cart_finalized_at)
        self.assertFalse(
            OrderReceipt.objects.filter(commande=payment.commande).exists()
        )

    def test_default_mode_is_a_dry_run(self):
        with patch(RETRIEVE, return_value=self.stripe_session()) as retrieve:
            stdout, stderr = self.run_command()

        retrieve.assert_called_once_with(self.payment.transaction_id)
        self.assert_payment_unchanged()
        self.assertTrue(CartItem.objects.filter(pk=self.cart_item.pk).exists())
        self.assertEqual(stderr, "")
        self.assertIn("Mode : LECTURE SEULE", stdout)
        self.assertIn("Paiements payés récupérables : 1", stdout)
        self.assertIn(
            "examinés=1, payés récupérés=0, ignorés=1, "
            "incompatibles=0, erreurs=0",
            stdout,
        )

    def test_apply_uses_existing_finalization_path(self):
        with patch(RETRIEVE, return_value=self.stripe_session()):
            stdout, _stderr = self.run_command(apply=True)

        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, "SUCCESS")
        self.assertEqual(self.order.payment_status, "SUCCESS")
        self.assertEqual(self.order.fulfillment_status, "TO_PREPARE")
        self.assertIsNotNone(self.order.cart_finalized_at)
        self.assertFalse(CartItem.objects.filter(pk=self.cart_item.pk).exists())
        self.assertEqual(OrderReceipt.objects.filter(commande=self.order).count(), 1)
        self.assertEqual(
            self.payment.raw_response,
            {
                "source": "stripe_payment_reconciliation",
                "payment_status": "paid",
            },
        )
        self.assertIn("payés récupérés=1", stdout)

    def test_incorrect_metadata_is_incompatible(self):
        metadata_variants = (
            {},
            {
                "commande_id": "999999",
                "payment_id": str(self.payment.id),
                "user_id": str(self.user.id),
            },
            {
                "commande_id": str(self.order.id),
                "payment_id": "999999",
                "user_id": str(self.user.id),
            },
            {
                "commande_id": str(self.order.id),
                "payment_id": str(self.payment.id),
                "user_id": "999999",
            },
        )

        for metadata in metadata_variants:
            with self.subTest(metadata=metadata), patch(
                RETRIEVE,
                return_value=self.stripe_session(metadata=metadata),
            ):
                stdout, _stderr = self.run_command(apply=True)
                self.assert_payment_unchanged()
                self.assertIn("incompatibles=1", stdout)

    def test_wrong_session_amount_or_currency_is_incompatible(self):
        mismatches = (
            {"id": "cs_unrelated"},
            {"amount_total": 1999},
            {"currency": "usd"},
        )

        for overrides in mismatches:
            with self.subTest(overrides=overrides), patch(
                RETRIEVE,
                return_value=self.stripe_session(**overrides),
            ):
                stdout, _stderr = self.run_command(apply=True)
                self.assert_payment_unchanged()
                self.assertIn("incompatibles=1", stdout)

    def test_local_order_amount_currency_and_association_must_still_match(self):
        changes = (
            {"total": Decimal("19.00")},
            {"currency": "USD"},
            {"transaction_id": "cs_other_local"},
            {"payment_channel": "CINETPAY"},
        )

        for fields in changes:
            with self.subTest(fields=fields):
                original = {name: getattr(self.order, name) for name in fields}
                Commande.objects.filter(pk=self.order.pk).update(**fields)
                with patch(RETRIEVE, return_value=self.stripe_session()):
                    stdout, _stderr = self.run_command(apply=True)
                self.assert_payment_unchanged()
                self.assertIn("incompatibles=1", stdout)
                Commande.objects.filter(pk=self.order.pk).update(**original)
                self.order.refresh_from_db()

    def test_open_and_expired_sessions_are_ignored_even_if_marked_paid(self):
        for status in ("open", "expired"):
            with self.subTest(status=status), patch(
                RETRIEVE,
                return_value=self.stripe_session(status=status),
            ):
                stdout, _stderr = self.run_command(apply=True)
                self.assert_payment_unchanged()
                self.assertIn("ignorés=1", stdout)
                self.assertIn("incompatibles=0", stdout)

    def test_expected_stripe_error_is_safe_and_does_not_stop_following_payment(self):
        _user, second_order, second_payment, second_item = self.create_bundle()
        provider_secret = "sk_live_secret provider@example.test cs_sensitive"
        error = stripe.APIConnectionError(provider_secret)

        with patch(
            RETRIEVE,
            side_effect=[error, self.stripe_session(second_payment)],
        ) as retrieve:
            stdout, stderr = self.run_command(apply=True)

        self.assertEqual(retrieve.call_count, 2)
        self.assert_payment_unchanged(self.payment)
        second_payment.refresh_from_db()
        second_order.refresh_from_db()
        self.assertEqual(second_payment.status, "SUCCESS")
        self.assertEqual(second_order.payment_status, "SUCCESS")
        self.assertFalse(CartItem.objects.filter(pk=second_item.pk).exists())
        self.assertIn("examinés=2", stdout)
        self.assertIn("payés récupérés=1", stdout)
        self.assertIn("erreurs=1", stdout)
        self.assertIn("APIConnectionError", stderr)
        self.assertNotIn(provider_secret, stderr)
        self.assertNotIn(self.payment.transaction_id, stderr)
        self.assertNotIn(self.user.email, stderr)

    def test_state_is_rechecked_under_lock_before_confirmation(self):
        def provider_response(_session_id):
            Payment.objects.filter(pk=self.payment.pk).update(status="FAILED")
            return self.stripe_session()

        with patch(RETRIEVE, side_effect=provider_response):
            stdout, _stderr = self.run_command(apply=True)

        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, "FAILED")
        self.assertEqual(self.order.payment_status, "PROCESSING")
        self.assertIsNone(self.order.cart_finalized_at)
        self.assertTrue(CartItem.objects.filter(pk=self.cart_item.pk).exists())
        self.assertFalse(OrderReceipt.objects.filter(commande=self.order).exists())
        self.assertIn("incompatibles=1", stdout)

    def test_rerun_is_idempotent_and_keeps_one_receipt(self):
        with patch(RETRIEVE, return_value=self.stripe_session()) as first_retrieve:
            first_stdout, _stderr = self.run_command(apply=True)

        receipt = OrderReceipt.objects.get(commande=self.order)
        receipt_identity = (receipt.pk, receipt.public_id, receipt.issued_at)

        with patch(RETRIEVE) as second_retrieve:
            second_stdout, _stderr = self.run_command(apply=True)

        first_retrieve.assert_called_once()
        second_retrieve.assert_not_called()
        receipt.refresh_from_db()
        self.assertEqual(
            (receipt.pk, receipt.public_id, receipt.issued_at), receipt_identity
        )
        self.assertEqual(OrderReceipt.objects.filter(commande=self.order).count(), 1)
        self.assertIn("payés récupérés=1", first_stdout)
        self.assertIn("examinés=0", second_stdout)
        self.assertIn("payés récupérés=0", second_stdout)

    def test_only_old_real_stripe_processing_sessions_are_examined(self):
        self.payment.status = "FAILED"
        self.payment.save(update_fields=["status", "updated_at"])
        terminal_ids = []
        for status in ("FAILED", "CANCELED", "SUCCESS"):
            _user, _order, payment, _item = self.create_bundle()
            Payment.objects.filter(pk=payment.pk).update(status=status)
            terminal_ids.append(payment.pk)
        self.create_bundle(session_id="pending_local_reference")
        self.create_bundle(age_minutes=5)
        _user, _order, other_channel, _item = self.create_bundle()
        Payment.objects.filter(pk=other_channel.pk).update(channel="CINETPAY")

        with patch(RETRIEVE) as retrieve:
            stdout, _stderr = self.run_command()

        retrieve.assert_not_called()
        self.assertIn("examinés=0", stdout)
        self.assertEqual(
            set(
                Payment.objects.filter(pk__in=terminal_ids).values_list(
                    "status", flat=True
                )
            ),
            {"FAILED", "CANCELED", "SUCCESS"},
        )

    def test_limit_and_age_options_are_honored(self):
        _user, _order, second_payment, _item = self.create_bundle(age_minutes=10)

        with patch(
            RETRIEVE,
            side_effect=lambda session_id: (
                self.stripe_session(self.payment)
                if session_id == self.payment.transaction_id
                else self.stripe_session(second_payment)
            ),
        ) as retrieve:
            stdout, _stderr = self.run_command(
                older_than_minutes=5,
                limit=1,
            )

        retrieve.assert_called_once()
        self.assertIn("examinés=1", stdout)

    def test_non_positive_options_are_rejected_before_stripe(self):
        for option in ({"limit": 0}, {"older_than_minutes": 0}):
            with self.subTest(option=option), patch(RETRIEVE) as retrieve:
                with self.assertRaises(CommandError):
                    self.run_command(**option)
                retrieve.assert_not_called()
