import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection
from django.db.backends.postgresql.base import DatabaseWrapper
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from payments.models import Adresse
from shop.admin import OrderFulfillmentEventAdmin
from shop.fulfillment import (
    InvalidFulfillmentTransition,
    PaymentNotConfirmed,
    ShippingDetailsInvalid,
    transition_order_fulfillment,
)
from shop.models import (
    Commande,
    LigneCommande,
    OrderCancellation,
    OrderFulfillmentEvent,
    Produit,
    StockMovement,
)
from shop.services import execute_with_sqlite_lock_retry


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="shop@example.test",
    SITE_BASE_URL="https://example.test",
)
class OrderFulfillmentIntegrityTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            email="fulfillment-integrity-staff@example.test",
            password="test-password",
            is_staff=True,
        )
        self.customer = user_model.objects.create_user(
            email="fulfillment-integrity-customer@example.test",
            password="test-password",
        )
        self.other_customer = user_model.objects.create_user(
            email="fulfillment-integrity-other@example.test",
            password="test-password",
        )
        self.address = Adresse.objects.create(
            utilisateur=self.customer,
            rue="1 rue Logistique",
            ville="Berlin",
            code_postal="10115",
            pays="Allemagne",
        )
        self.product = Produit.objects.create(
            nom="Produit physique logistique",
            slug="produit-physique-logistique",
            prix=Decimal("20.00"),
            stock=5,
        )
        self.order = Commande.objects.create(
            client=self.customer,
            adresse=self.address,
            total=Decimal("20.00"),
            payment_status="SUCCESS",
            fulfillment_status="TO_PREPARE",
            inventory_status="COMMITTED",
        )
        LigneCommande.objects.create(
            commande=self.order,
            produit=self.product,
            quantite=1,
            prix_unitaire=self.product.prix,
        )

    def transition(self, status, **kwargs):
        return transition_order_fulfillment(
            self.order.pk,
            status,
            actor=self.staff,
            idempotency_key=kwargs.pop("idempotency_key", uuid.uuid4()),
            **kwargs,
        )

    def test_valid_transitions_create_append_only_events_without_stock_change(self):
        initial_stock = self.product.stock
        initial_movements = StockMovement.objects.count()

        self.transition("PREPARING", note="  Contrôle qualité effectué  ")
        self.transition(
            "SHIPPED",
            carrier="  DHL   Express  ",
            tracking_number="  TRACK-123  ",
        )
        self.transition("DELIVERED")

        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, "DELIVERED")
        self.assertEqual(self.product.stock, initial_stock)
        self.assertEqual(StockMovement.objects.count(), initial_movements)
        self.assertEqual(
            list(
                self.order.fulfillment_events.values_list(
                    "old_status", "new_status"
                )
            ),
            [
                ("TO_PREPARE", "PREPARING"),
                ("PREPARING", "SHIPPED"),
                ("SHIPPED", "DELIVERED"),
            ],
        )
        shipped_event = self.order.fulfillment_events.get(new_status="SHIPPED")
        self.assertEqual(shipped_event.carrier, "DHL Express")
        self.assertEqual(shipped_event.tracking_number, "TRACK-123")
        self.assertIn("dhl", shipped_event.tracking_url.lower())
        self.assertEqual(
            self.order.fulfillment_events.get(new_status="PREPARING").note,
            "Contrôle qualité effectué",
        )

    def test_unpaid_canceled_skipped_reversed_and_delivered_orders_are_refused(self):
        self.order.payment_status = "PENDING"
        self.order.save(update_fields=["payment_status"])
        with self.assertRaises(PaymentNotConfirmed):
            self.transition("PREPARING")

        self.order.payment_status = "SUCCESS"
        self.order.save(update_fields=["payment_status"])
        with self.assertRaises(InvalidFulfillmentTransition):
            self.transition("SHIPPED", carrier="DHL", tracking_number="SKIP")

        self.transition("PREPARING")
        with self.assertRaises(InvalidFulfillmentTransition):
            self.transition("TO_PREPARE")

        OrderCancellation.objects.create(
            commande=self.order,
            requested_by=self.staff,
            source="STAFF",
        )
        with self.assertRaises(InvalidFulfillmentTransition):
            self.transition("SHIPPED", carrier="DHL", tracking_number="CANCEL")

        OrderCancellation.objects.filter(commande=self.order).delete()
        self.transition("SHIPPED", carrier="DHL", tracking_number="FINAL")
        self.transition("DELIVERED")
        with self.assertRaises(InvalidFulfillmentTransition):
            self.transition("SHIPPED", carrier="DHL", tracking_number="BACK")
        self.assertEqual(self.order.fulfillment_events.count(), 3)

    def test_physical_shipping_requires_normalized_tracking(self):
        self.transition("PREPARING")
        for carrier, tracking in (("", "TRACK"), ("DHL", "")):
            with self.subTest(carrier=carrier, tracking=tracking):
                with self.assertRaises(ShippingDetailsInvalid):
                    self.transition(
                        "SHIPPED",
                        carrier=carrier,
                        tracking_number=tracking,
                    )
        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, "PREPARING")

    def test_digital_only_order_is_delivered_without_physical_shipping(self):
        digital = Produit.objects.create(
            nom="Guide numérique",
            slug="guide-numerique-fulfillment",
            prix=Decimal("10.00"),
            fichier="produits/fichiers/guide.pdf",
        )
        digital_order = Commande.objects.create(
            client=self.customer,
            adresse=self.address,
            total=Decimal("10.00"),
            payment_status="SUCCESS",
            fulfillment_status="PREPARING",
        )
        LigneCommande.objects.create(
            commande=digital_order,
            produit=digital,
            quantite=1,
            prix_unitaire=digital.prix,
        )

        with self.captureOnCommitCallbacks(execute=True):
            delivered = transition_order_fulfillment(
                digital_order.pk,
                "DELIVERED",
                actor=self.staff,
                idempotency_key=uuid.uuid4(),
            )

        self.assertTrue(digital_order.is_digital_only)
        self.assertEqual(delivered.fulfillment_status, "DELIVERED")
        self.assertEqual(delivered.carrier, "")
        self.assertEqual(delivered.tracking_number, "")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("livrée", mail.outbox[0].subject)

    def test_refund_preserves_and_blocks_current_fulfillment_state(self):
        self.order.fulfillment_status = "PREPARING"
        self.order.payment_status = "REFUNDED"
        self.order.save(update_fields=["fulfillment_status", "payment_status"])

        with self.assertRaises(PaymentNotConfirmed):
            self.transition("SHIPPED", carrier="DHL", tracking_number="REFUND")

        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, "PREPARING")
        self.assertEqual(self.order.payment_status, "REFUNDED")
        self.assertFalse(OrderFulfillmentEvent.objects.exists())

    def test_service_and_views_enforce_staff_post_and_csrf(self):
        with self.assertRaises(PermissionDenied):
            transition_order_fulfillment(
                self.order.pk,
                "PREPARING",
                actor=self.customer,
            )

        url = reverse("shop:commande_traitement_modifier", args=[self.order.pk])
        self.client.force_login(self.customer)
        self.client.post(url, {"statut": "PREPARING"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, "TO_PREPARE")

        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        self.assertEqual(
            csrf_client.post(url, {"statut": "PREPARING"}).status_code,
            403,
        )

    def test_repeated_transition_creates_one_event_and_one_email(self):
        self.order.fulfillment_status = "PREPARING"
        self.order.save(update_fields=["fulfillment_status"])
        key = uuid.uuid4()

        with self.captureOnCommitCallbacks(execute=True):
            first = self.transition(
                "SHIPPED",
                carrier="DHL",
                tracking_number="IDEMPOTENT",
                idempotency_key=key,
            )
            second = self.transition(
                "SHIPPED",
                carrier="DHL",
                tracking_number="IDEMPOTENT",
                idempotency_key=key,
            )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(OrderFulfillmentEvent.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_postgresql_lock_compiles_for_only_order_without_join(self):
        captured = {}
        real_select_for_update = Commande.objects.select_for_update

        def capture_lock(*args, **kwargs):
            queryset = real_select_for_update(*args, **kwargs)
            captured["queryset"] = queryset
            return queryset

        with patch.object(
            Commande.objects,
            "select_for_update",
            side_effect=capture_lock,
        ) as lock:
            self.transition("PREPARING")
        queryset = captured["queryset"]
        self.assertEqual(lock.call_args.kwargs, {"of": ("self",)})

        postgres = DatabaseWrapper(
            {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "compile_only",
                "USER": "",
                "PASSWORD": "",
                "HOST": "",
                "PORT": "",
                "OPTIONS": {},
                "TIME_ZONE": None,
                "CONN_HEALTH_CHECKS": False,
                "CONN_MAX_AGE": 0,
                "AUTOCOMMIT": True,
            },
            alias="fulfillment_postgresql_compile_only",
        )
        with patch.object(postgres, "get_autocommit", return_value=False):
            sql, _params = queryset.filter(pk=self.order.pk).query.get_compiler(
                connection=postgres
            ).as_sql()
        sql = sql.upper()
        self.assertIn('FOR UPDATE OF "SHOP_COMMANDE"', sql)
        self.assertNotIn(" JOIN ", sql)

    def test_journal_is_immutable_and_admin_is_read_only(self):
        self.transition("PREPARING")
        event = OrderFulfillmentEvent.objects.get()
        event.note = "altération"
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()
        with self.assertRaises(ValidationError):
            OrderFulfillmentEvent.objects.filter(pk=event.pk).update(note="x")
        model_admin = admin.site._registry[OrderFulfillmentEvent]
        self.assertIsInstance(model_admin, OrderFulfillmentEventAdmin)
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None, event))
        self.assertFalse(model_admin.has_delete_permission(None, event))

    def test_owner_sees_tracking_and_timeline_but_other_customer_does_not(self):
        self.order.fulfillment_status = "PREPARING"
        self.order.save(update_fields=["fulfillment_status"])
        self.transition("SHIPPED", carrier="DHL", tracking_number="PRIVATE-TRACK")

        self.client.force_login(self.customer)
        own = self.client.get(
            reverse("shop:ma_commande_detail", args=[self.order.pk])
        )
        self.assertContains(own, "PRIVATE-TRACK")
        self.assertContains(own, "Chronologie logistique")

        self.client.force_login(self.other_customer)
        other = self.client.get(
            reverse("shop:ma_commande_detail", args=[self.order.pk])
        )
        self.assertEqual(other.status_code, 404)
        self.assertNotContains(other, "PRIVATE-TRACK", status_code=404)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="shop@example.test",
)
class OrderFulfillmentConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_concurrent_same_transition_creates_one_event(self):
        user_model = get_user_model()
        staff = user_model.objects.create_user(
            email="fulfillment-concurrency-staff@example.test",
            is_staff=True,
        )
        customer = user_model.objects.create_user(
            email="fulfillment-concurrency-customer@example.test"
        )
        product = Produit.objects.create(
            nom="Produit concurrence logistique",
            slug="produit-concurrence-logistique",
            prix=Decimal("10.00"),
        )
        order = Commande.objects.create(
            client=customer,
            total=Decimal("10.00"),
            payment_status="SUCCESS",
            fulfillment_status="TO_PREPARE",
        )
        LigneCommande.objects.create(
            commande=order,
            produit=product,
            quantite=1,
            prix_unitaire=product.prix,
        )
        key = uuid.uuid4()
        barrier = Barrier(2)

        def advance():
            close_old_connections()
            barrier.wait()
            execute_with_sqlite_lock_retry(
                lambda: transition_order_fulfillment(
                    order.pk,
                    "PREPARING",
                    actor=staff,
                    idempotency_key=key,
                ),
                attempts=10,
                base_delay=0.01,
            )
            close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(advance), executor.submit(advance)]
            for future in futures:
                future.result()

        order.refresh_from_db()
        self.assertEqual(order.fulfillment_status, "PREPARING")
        self.assertEqual(OrderFulfillmentEvent.objects.count(), 1)


class OrderFulfillmentMigrationTests(TransactionTestCase):
    migrate_from = [("shop", "0023_order_cancellation_integrity")]
    migrate_to = [("shop", "0024_order_fulfillment_integrity")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        apps = executor.loader.project_state(self.migrate_from).apps
        User = apps.get_model("accounts", "CustomUser")
        CommandeModel = apps.get_model("shop", "Commande")
        user = User.objects.create(email="fulfillment-migration@example.test")
        self.order_id = CommandeModel.objects.create(
            client=user,
            total=Decimal("20.00"),
            payment_status="SUCCESS",
            fulfillment_status="SHIPPED",
            carrier="DHL",
            tracking_number="HISTORICAL-TRACK",
        ).pk

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_forward_migration_snapshots_historical_state(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        Event = apps.get_model("shop", "OrderFulfillmentEvent")

        event = Event.objects.get(commande_id=self.order_id)
        self.assertEqual((event.old_status, event.new_status), ("SHIPPED", "SHIPPED"))
        self.assertEqual(event.tracking_number, "HISTORICAL-TRACK")
        self.assertIn("dhl", event.tracking_url.lower())

    def test_reverse_migration_preserves_historical_order(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        apps = executor.loader.project_state(self.migrate_from).apps
        CommandeModel = apps.get_model("shop", "Commande")

        order = CommandeModel.objects.get(pk=self.order_id)
        self.assertEqual(order.fulfillment_status, "SHIPPED")
        self.assertEqual(order.tracking_number, "HISTORICAL-TRACK")
