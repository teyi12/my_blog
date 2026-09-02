import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.test import TestCase
from django.urls import reverse

from payments.models import Adresse, Payment
from shop.models import Cart, CartItem, Commande, LigneCommande, Produit
from shop.services import (
    SQLiteLockRetryExhausted,
    execute_with_sqlite_lock_retry,
    finalize_paid_order,
)


class CheckoutFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="client@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.product = Produit.objects.create(
            nom="Produit initial",
            slug="produit-initial",
            prix=Decimal("12.50"),
        )
        self.new_product = Produit.objects.create(
            nom="Nouveau produit",
            slug="nouveau-produit",
            prix=Decimal("7.00"),
        )
        self.cart = Cart.objects.create(user=self.user)
        self.cart_item = CartItem.objects.create(
            cart=self.cart,
            produit=self.product,
            quantite=2,
            prix_unitaire=self.product.prix,
        )

    def checkout_data(self, token):
        return {
            "checkout_token": str(token),
            "rue": "1 rue du Test",
            "ville": "Paris",
            "code_postal": "75001",
            "pays": "France",
            "telephone": "0102030405",
        }

    def get_checkout_token(self):
        response = self.client.get(reverse("shop:checkout"))
        self.assertEqual(response.status_code, 200)
        return response.context["checkout_token"]

    def create_order(self):
        token = self.get_checkout_token()
        response = self.client.post(
            reverse("shop:checkout"),
            self.checkout_data(token),
        )
        self.assertEqual(response.status_code, 302)
        return Commande.objects.get(checkout_token=token)

    def test_checkout_creates_one_complete_order_atomically(self):
        order = self.create_order()

        self.assertEqual(order.client, self.user)
        self.assertEqual(order.source_cart, self.cart)
        self.assertEqual(order.total, Decimal("25.00"))
        self.assertEqual(order.payment_status, "PENDING")
        self.assertEqual(Adresse.objects.filter(utilisateur=self.user).count(), 1)
        line = LigneCommande.objects.get(commande=order)
        self.assertEqual(line.source_cart_item, self.cart_item)
        self.assertEqual(line.quantite, 2)
        self.assertEqual(line.prix_unitaire, Decimal("12.50"))

    def test_double_checkout_post_reuses_the_same_order(self):
        token = self.get_checkout_token()
        data = self.checkout_data(token)

        first_response = self.client.post(reverse("shop:checkout"), data)
        second_response = self.client.post(reverse("shop:checkout"), data)

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(Commande.objects.filter(checkout_token=token).count(), 1)
        self.assertEqual(Adresse.objects.filter(utilisateur=self.user).count(), 1)
        self.assertEqual(LigneCommande.objects.count(), 1)

    def test_cart_changes_after_checkout_do_not_change_the_order(self):
        order = self.create_order()
        CartItem.objects.filter(pk=self.cart_item.pk).update(quantite=3)
        CartItem.objects.create(
            cart=self.cart,
            produit=self.new_product,
            quantite=1,
            prix_unitaire=self.new_product.prix,
        )

        line = order.lignes.get()
        self.assertEqual(line.quantite, 2)
        self.assertEqual(order.total, Decimal("25.00"))

    def test_finalization_removes_only_ordered_items_and_is_idempotent(self):
        order = self.create_order()
        CartItem.objects.filter(pk=self.cart_item.pk).update(quantite=3)
        new_item = CartItem.objects.create(
            cart=self.cart,
            produit=self.new_product,
            quantite=1,
            prix_unitaire=self.new_product.prix,
        )

        finalize_paid_order(order.id)
        finalize_paid_order(order.id)

        self.cart_item.refresh_from_db()
        new_item.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.cart_item.quantite, 1)
        self.assertEqual(new_item.quantite, 1)
        self.assertEqual(order.payment_status, "SUCCESS")
        self.assertIsNotNone(order.cart_finalized_at)

    def test_sqlite_lock_is_retried_and_unrelated_operational_error_is_not(self):
        operation = Mock(side_effect=[OperationalError("database is locked"), "ok"])
        with patch("shop.services.time.sleep") as sleep:
            self.assertEqual(execute_with_sqlite_lock_retry(operation), "ok")
        self.assertEqual(operation.call_count, 2)
        sleep.assert_called_once()

        unrelated = Mock(side_effect=OperationalError("no such table: example"))
        with self.assertRaises(OperationalError):
            execute_with_sqlite_lock_retry(unrelated)
        self.assertEqual(unrelated.call_count, 1)

    def test_checkout_lock_exhaustion_returns_conflict_not_500(self):
        token = self.get_checkout_token()
        with patch(
            "shop.views.execute_with_sqlite_lock_retry",
            side_effect=SQLiteLockRetryExhausted,
        ):
            response = self.client.post(
                reverse("shop:checkout"),
                self.checkout_data(token),
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(Commande.objects.filter(checkout_token=token).count(), 0)

    def test_checkout_recovers_winning_order_after_lock_collision(self):
        token = self.get_checkout_token()
        address = Adresse.objects.create(
            utilisateur=self.user,
            rue="1 rue du Test",
            ville="Paris",
            code_postal="75001",
            pays="France",
        )
        winning_order = Commande.objects.create(
            client=self.user,
            adresse=address,
            source_cart=self.cart,
            checkout_token=token,
            total=Decimal("25.00"),
        )

        calls = 0

        def simulate_collision(operation):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise SQLiteLockRetryExhausted
            return operation()

        with patch(
            "shop.views.execute_with_sqlite_lock_retry",
            side_effect=simulate_collision,
        ):
            response = self.client.post(
                reverse("shop:checkout"),
                self.checkout_data(token),
            )

        self.assertRedirects(
            response,
            f"{reverse('shop:adresse_enregistree')}?order_id={winning_order.id}",
            fetch_redirect_response=False,
        )
        self.assertEqual(Commande.objects.filter(checkout_token=token).count(), 1)

    def test_recreated_source_item_is_not_removed(self):
        order = self.create_order()
        self.cart_item.delete()
        recreated = CartItem.objects.create(
            cart=self.cart,
            produit=self.product,
            quantite=4,
            prix_unitaire=self.product.prix,
        )

        finalize_paid_order(order.id)

        recreated.refresh_from_db()
        self.assertEqual(recreated.quantite, 4)

    def test_second_finalization_does_not_consume_cart_again(self):
        order = self.create_order()
        CartItem.objects.filter(pk=self.cart_item.pk).update(quantite=3)

        finalize_paid_order(order.id)
        self.cart_item.refresh_from_db()
        quantity_after_first_finalization = self.cart_item.quantite
        finalize_paid_order(order.id)
        self.cart_item.refresh_from_db()

        self.assertEqual(quantity_after_first_finalization, 1)
        self.assertEqual(self.cart_item.quantite, 1)

    def test_finalization_retries_sqlite_lock(self):
        order = self.create_order()
        from shop import services

        finalize_once = services._finalize_paid_order_once
        calls = 0

        def lock_then_finalize(order_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OperationalError("database is locked")
            return finalize_once(order_id)

        with patch(
            "shop.services._finalize_paid_order_once",
            side_effect=lock_then_finalize,
        ), patch("shop.services.time.sleep"):
            finalized = finalize_paid_order(order.id)

        self.assertEqual(calls, 2)
        self.assertEqual(finalized.payment_status, "SUCCESS")

    def test_stripe_webhook_returns_409_when_sqlite_lock_persists(self):
        order = self.create_order()
        payment = Payment.objects.create(
            commande=order,
            montant=order.total,
            devise=order.currency,
            transaction_id="cs_test_session",
            channel="STRIPE",
            status="PROCESSING",
        )
        order.transaction_id = payment.transaction_id
        order.payment_status = "PROCESSING"
        order.save(update_fields=["transaction_id", "payment_status"])
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": payment.transaction_id,
                    "payment_status": "paid",
                    "amount_total": 25,
                    "currency": order.currency.lower(),
                    "metadata": {
                        "commande_id": str(order.id),
                        "user_id": str(self.user.id),
                        "payment_id": str(payment.id),
                    }
                }
            },
        }

        with patch("payments.views.stripe.Webhook.construct_event", return_value=event), patch(
            "payments.views.finalize_paid_order",
            side_effect=SQLiteLockRetryExhausted,
        ):
            response = self.client.post(
                reverse("payments:stripe_webhook"),
                data=b"{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="signature",
            )

        self.assertEqual(response.status_code, 409)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "PROCESSING")

    def test_cinetpay_ipn_returns_409_when_sqlite_lock_persists(self):
        order = self.create_order()
        order.transaction_id = "cinetpay-transaction"
        order.payment_status = "PROCESSING"
        order.save(update_fields=["transaction_id", "payment_status"])
        Payment.objects.create(
            commande=order,
            montant=order.total,
            devise=order.currency,
            transaction_id=order.transaction_id,
            channel="CINETPAY",
            status="PROCESSING",
        )

        provider_data = {
            "status": "ACCEPTED",
            "transaction_id": order.transaction_id,
            "amount": str(order.total),
            "currency": order.currency,
        }
        with patch("payments.views._cinetpay_check_status", return_value=provider_data), patch(
            "payments.views.finalize_paid_order",
            side_effect=SQLiteLockRetryExhausted,
        ):
            response = self.client.post(
                reverse("payments:cinetpay_ipn"),
                data=json.dumps({"transaction_id": order.transaction_id}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 409)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "PROCESSING")
