import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import (
    IntegrityError,
    close_old_connections,
    connection,
    transaction,
)
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from payments.models import Adresse, Payment
from payments.refunds import request_full_refund
from shop.inventory import StockUnavailable, reserve_order_stock
from shop.models import Cart, CartItem, Commande, LigneCommande, Produit
from shop.services import execute_with_sqlite_lock_retry


CONSTRUCT_EVENT = "payments.views.stripe.Webhook.construct_event"
CINETPAY_STATUS = "payments.views._cinetpay_check_status"
RECONCILE_RETRIEVE = (
    "payments.management.commands.reconcile_stripe_payments."
    "stripe.checkout.Session.retrieve"
)


class InventoryIntegrityTests(TestCase):
    def setUp(self):
        self.counter = 0
        self.user = self.create_user()
        self.client.force_login(self.user)

    def create_user(self):
        self.counter += 1
        return get_user_model().objects.create_user(
            email=f"inventory-{self.counter}@example.test",
            password="test-password",
        )

    def create_product(self, *, stock=5, digital=False):
        self.counter += 1
        return Produit.objects.create(
            nom=f"Produit stock {self.counter}",
            slug=f"produit-stock-{self.counter}",
            prix=Decimal("20.00"),
            stock=stock,
            fichier=(
                f"produits/fichiers/digital-{self.counter}.pdf"
                if digital
                else None
            ),
        )

    def create_order_bundle(
        self,
        *,
        product=None,
        quantity=1,
        channel="STRIPE",
        reserve=True,
    ):
        product = product or self.create_product()
        user = self.create_user()
        cart = Cart.objects.create(user=user)
        item = CartItem.objects.create(
            cart=cart,
            produit=product,
            quantite=quantity,
            prix_unitaire=product.prix,
        )
        address = Adresse.objects.create(
            utilisateur=user,
            rue="1 rue du Stock",
            ville="Paris",
            code_postal="75001",
            pays="France",
        )
        order = Commande.objects.create(
            client=user,
            adresse=address,
            source_cart=cart,
            total=product.prix * quantity,
            currency="EUR",
        )
        line = LigneCommande.objects.create(
            commande=order,
            produit=product,
            source_cart_item=item,
            quantite=quantity,
            prix_unitaire=product.prix,
        )
        if reserve:
            reserve_order_stock(order.id)
        transaction_id = (
            f"cs_inventory_{order.id}"
            if channel == "STRIPE"
            else f"cinetpay_inventory_{order.id}"
        )
        payment = Payment.objects.create(
            commande=order,
            montant=order.total,
            devise=order.currency,
            transaction_id=transaction_id,
            channel=channel,
            status="PROCESSING",
        )
        order.payment_status = "PROCESSING"
        order.payment_channel = channel
        order.transaction_id = transaction_id
        order.save(
            update_fields=[
                "payment_status",
                "payment_channel",
                "transaction_id",
            ]
        )
        return user, product, cart, item, order, line, payment

    def stripe_event(self, order, payment, *, event_type="checkout.session.completed"):
        return {
            "id": f"evt_inventory_{order.id}_{event_type}",
            "type": event_type,
            "data": {
                "object": {
                    "id": payment.transaction_id,
                    "status": (
                        "expired"
                        if event_type == "checkout.session.expired"
                        else "complete"
                    ),
                    "payment_status": (
                        "paid"
                        if event_type == "checkout.session.completed"
                        else "unpaid"
                    ),
                    "amount_total": int(order.total * 100),
                    "currency": order.currency.lower(),
                    "metadata": {
                        "commande_id": str(order.id),
                        "payment_id": str(payment.id),
                        "user_id": str(order.client_id),
                    },
                }
            },
        }

    def post_stripe_event(self, event):
        with patch(CONSTRUCT_EVENT, return_value=event):
            return self.client.post(
                reverse("payments:stripe_webhook"),
                data=b"{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="signature",
            )

    def test_zero_and_insufficient_stock_block_cart_addition(self):
        product = self.create_product(stock=0)
        response = self.client.post(
            reverse("shop:ajouter_panier", args=[product.slug])
        )
        self.assertRedirects(response, reverse("shop:panier"))
        self.assertFalse(CartItem.objects.filter(produit=product).exists())

        product.stock = 2
        product.save(update_fields=["stock"])
        cart = Cart.objects.get(user=self.user)
        item = CartItem.objects.create(
            cart=cart,
            produit=product,
            quantite=2,
        )
        self.client.post(reverse("shop:ajouter_panier", args=[product.slug]))
        item.refresh_from_db()
        self.assertEqual(item.quantite, 2)

    def test_forged_quantity_post_is_rejected_and_scoped_to_active_cart(self):
        product = self.create_product(stock=3)
        cart = Cart.objects.create(user=self.user)
        item = CartItem.objects.create(cart=cart, produit=product, quantite=1)
        response = self.client.post(
            reverse("shop:update_panier"),
            data=json.dumps(
                {"action": "modifier", "item_id": item.id, "quantite": 999}
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["available"], 3)
        item.refresh_from_db()
        self.assertEqual(item.quantite, 1)

        other_user = self.create_user()
        other_cart = Cart.objects.create(user=other_user)
        other_item = CartItem.objects.create(
            cart=other_cart,
            produit=product,
            quantite=1,
        )
        response = self.client.post(
            reverse("shop:update_panier"),
            data=json.dumps(
                {
                    "action": "modifier",
                    "item_id": other_item.id,
                    "quantite": 2,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        other_item.refresh_from_db()
        self.assertEqual(other_item.quantite, 1)

    def test_cart_update_keeps_csrf_protection(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(
            reverse("shop:update_panier"),
            data=b"{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_checkout_rejects_a_cart_that_became_unavailable(self):
        product = self.create_product(stock=2)
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, produit=product, quantite=2)
        checkout_url = reverse("shop:checkout")
        token = self.client.get(checkout_url).context["checkout_token"]
        product.stock = 1
        product.save(update_fields=["stock"])

        response = self.client.post(
            checkout_url,
            {
                "checkout_token": str(token),
                "rue": "1 rue du Test",
                "ville": "Paris",
                "code_postal": "75001",
                "pays": "France",
                "telephone": "0102030405",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Commande.objects.exists())
        self.assertFalse(Adresse.objects.exists())

    def test_payment_start_rechecks_stock_before_provider_call(self):
        user, product, _cart, _item, order, _line, _payment = (
            self.create_order_bundle(reserve=False)
        )
        product.stock = 0
        product.save(update_fields=["stock"])
        self.client.force_login(user)
        with patch(
            "payments.views.stripe.checkout.Session.create"
        ) as create_session:
            response = self.client.post(
                reverse("payments:stripe_checkout", args=[order.id])
            )

        self.assertEqual(response.status_code, 409)
        create_session.assert_not_called()
        product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(product.stock, 0)
        self.assertEqual(order.inventory_status, "NONE")

    def test_stripe_webhook_is_idempotent_and_decrements_only_once(self):
        user, product, _cart, _item, order, line, payment = (
            self.create_order_bundle(quantity=2)
        )
        product.refresh_from_db()
        self.assertEqual(product.stock, 3)

        event = self.stripe_event(order, payment)
        first = self.post_stripe_event(event)
        second = self.post_stripe_event(event)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        product.refresh_from_db()
        order.refresh_from_db()
        line.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(product.stock, 3)
        self.assertEqual(order.inventory_status, "COMMITTED")
        self.assertEqual(line.stock_reserved_quantity, 2)
        self.assertEqual(payment.status, "SUCCESS")
        self.assertEqual(order.client, user)

    def test_cinetpay_confirmation_commits_without_second_decrement(self):
        _user, product, _cart, _item, order, _line, payment = (
            self.create_order_bundle(channel="CINETPAY")
        )
        provider_data = {
            "status": "ACCEPTED",
            "amount": str(order.total),
            "currency": order.currency,
        }
        with patch(CINETPAY_STATUS, return_value=provider_data):
            response = self.client.post(
                reverse("payments:cinetpay_ipn"),
                {"transaction_id": payment.transaction_id},
            )
        self.assertEqual(response.status_code, 200)
        product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(product.stock, 4)
        self.assertEqual(order.inventory_status, "COMMITTED")

    def test_failed_canceled_and_expired_payments_release_stock(self):
        stripe_events = (
            "checkout.session.async_payment_failed",
            "checkout.session.expired",
        )
        for event_type in stripe_events:
            with self.subTest(event_type=event_type):
                _user, product, _cart, _item, order, line, payment = (
                    self.create_order_bundle()
                )
                response = self.post_stripe_event(
                    self.stripe_event(order, payment, event_type=event_type)
                )
                self.assertEqual(response.status_code, 200)
                product.refresh_from_db()
                order.refresh_from_db()
                line.refresh_from_db()
                self.assertEqual(product.stock, 5)
                self.assertEqual(order.inventory_status, "RELEASED")
                self.assertEqual(line.stock_reserved_quantity, 0)

        _user, product, _cart, _item, order, _line, payment = (
            self.create_order_bundle(channel="CINETPAY")
        )
        with patch(
            CINETPAY_STATUS,
            return_value={
                "status": "CANCELED",
                "amount": str(order.total),
                "currency": order.currency,
            },
        ):
            response = self.client.post(
                reverse("payments:cinetpay_ipn"),
                {"transaction_id": payment.transaction_id},
            )
        self.assertEqual(response.status_code, 200)
        product.refresh_from_db()
        self.assertEqual(product.stock, 5)

    def test_reconciliation_does_not_decrement_reserved_stock_twice(self):
        _user, product, _cart, _item, order, _line, payment = (
            self.create_order_bundle()
        )
        Payment.objects.filter(pk=payment.pk).update(
            updated_at=timezone.now() - timedelta(minutes=61)
        )
        session = self.stripe_event(order, payment)["data"]["object"]
        stdout = StringIO()
        with patch(RECONCILE_RETRIEVE, return_value=session):
            call_command(
                "reconcile_stripe_payments",
                apply=True,
                stdout=stdout,
            )
        product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(product.stock, 4)
        self.assertEqual(order.inventory_status, "COMMITTED")
        self.assertIn("payés récupérés=1", stdout.getvalue())

    def test_expired_reservation_cleanup_is_safe_and_idempotent(self):
        _user, product, _cart, _item, order, _line, payment = (
            self.create_order_bundle()
        )
        payment.transaction_id = f"pending_{payment.id}"
        payment.save(update_fields=["transaction_id"])
        order.transaction_id = payment.transaction_id
        order.stock_reservation_expires_at = timezone.now() - timedelta(minutes=1)
        order.save(
            update_fields=[
                "transaction_id",
                "stock_reservation_expires_at",
            ]
        )

        dry_run = StringIO()
        call_command("release_expired_stock_reservations", stdout=dry_run)
        product.refresh_from_db()
        self.assertEqual(product.stock, 4)
        self.assertIn("Mode : LECTURE SEULE", dry_run.getvalue())

        applied = StringIO()
        call_command(
            "release_expired_stock_reservations",
            apply=True,
            stdout=applied,
        )
        call_command(
            "release_expired_stock_reservations",
            apply=True,
            stdout=StringIO(),
        )
        product.refresh_from_db()
        order.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(product.stock, 5)
        self.assertEqual(order.inventory_status, "RELEASED")
        self.assertEqual(payment.status, "CANCELED")
        self.assertIn("libérées=1", applied.getvalue())

    def test_refund_never_restores_committed_stock(self):
        _user, product, _cart, _item, order, _line, payment = (
            self.create_order_bundle()
        )
        self.post_stripe_event(self.stripe_event(order, payment))
        product.refresh_from_db()
        stock_after_payment = product.stock
        session = self.stripe_event(order, payment)["data"]["object"]
        session["payment_intent"] = f"pi_{payment.id}"

        def create_refund(**kwargs):
            return {
                "id": "re_inventory",
                "status": "succeeded",
                "payment_intent": kwargs["payment_intent"],
                "amount": kwargs["amount"],
                "currency": "eur",
                "metadata": kwargs["metadata"],
            }

        with patch(
            "payments.refunds.stripe.checkout.Session.retrieve",
            return_value=session,
        ), patch(
            "payments.refunds.stripe.Refund.create",
            side_effect=create_refund,
        ):
            request_full_refund(order.id, None)

        product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(product.stock, stock_after_payment)
        self.assertEqual(order.payment_status, "REFUNDED")
        self.assertEqual(order.inventory_status, "COMMITTED")

    def test_digital_product_ignores_stock_without_negative_value(self):
        product = self.create_product(stock=0, digital=True)
        add_url = reverse("shop:ajouter_panier", args=[product.slug])
        self.client.post(add_url)
        self.client.post(add_url)
        item = CartItem.objects.get(produit=product, cart__user=self.user)
        self.assertEqual(item.quantite, 2)

        _user, _product, _cart, _item, order, line, _payment = (
            self.create_order_bundle(product=product, quantity=2)
        )
        product.refresh_from_db()
        line.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(product.stock, 0)
        self.assertEqual(line.stock_reserved_quantity, 0)
        self.assertEqual(order.inventory_status, "RESERVED")

    def test_database_constraint_prevents_negative_stock(self):
        product = self.create_product(stock=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Produit.objects.filter(pk=product.pk).update(stock=-1)

    def test_storefront_and_cart_show_availability(self):
        product = self.create_product(stock=0)
        list_response = self.client.get(reverse("shop:liste"))
        self.assertContains(list_response, "Rupture de stock")

        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, produit=product, quantite=1)
        cart_response = self.client.get(reverse("shop:panier"))
        self.assertContains(cart_response, "Rupture de stock")
        self.assertContains(cart_response, "Panier indisponible")
        self.assertNotContains(
            cart_response,
            f'href="{reverse("shop:checkout")}"',
        )


class ConcurrentInventoryTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        product = Produit.objects.create(
            nom="Dernier article",
            slug="dernier-article",
            prix=Decimal("10.00"),
            stock=1,
        )
        self.order_ids = []
        for index in range(2):
            user = get_user_model().objects.create_user(
                email=f"concurrent-{index}@example.test",
                password="test-password",
            )
            order = Commande.objects.create(
                client=user,
                total=product.prix,
            )
            LigneCommande.objects.create(
                commande=order,
                produit=product,
                quantite=1,
                prix_unitaire=product.prix,
            )
            self.order_ids.append(order.id)
        self.product_id = product.id

    def test_two_buyers_cannot_reserve_the_last_item(self):
        barrier = Barrier(2)

        def attempt(order_id):
            close_old_connections()
            barrier.wait()
            try:
                execute_with_sqlite_lock_retry(
                    lambda: reserve_order_stock(order_id),
                    attempts=10,
                    base_delay=0.01,
                )
            except StockUnavailable:
                result = "StockUnavailable"
            else:
                result = "reserved"
            finally:
                close_old_connections()
            return result

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, self.order_ids))

        self.assertEqual(results.count("reserved"), 1)
        self.assertEqual(results.count("StockUnavailable"), 1)
        self.assertEqual(Produit.objects.get(pk=self.product_id).stock, 0)
        self.assertEqual(
            Commande.objects.filter(inventory_status="RESERVED").count(),
            1,
        )
