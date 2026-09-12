from decimal import Decimal
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from payments.models import Adresse
from shop.admin import CommandeAdmin
from shop.fulfillment import (
    InvalidFulfillmentTransition,
    PaymentNotConfirmed,
    ShippingDetailsInvalid,
    ShippingDetailsNotEditable,
    transition_order_fulfillment,
    update_order_shipping_details,
)
from shop.models import Commande, LigneCommande, Produit
from shop.shipping import send_fulfillment_notification


class FulfillmentServiceSecurityTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.customer = user_model.objects.create_user(
            email="fulfillment-customer@example.test",
            password="test-password",
        )
        self.address = Adresse.objects.create(
            utilisateur=self.customer,
            rue="1 rue du Colis",
            ville="Paris",
            code_postal="75001",
            pays="France",
        )
        self.product = Produit.objects.create(
            nom="Produit à expédier",
            slug="produit-a-expedier-securise",
            prix=Decimal("30.00"),
        )
        self.order = Commande.objects.create(
            client=self.customer,
            adresse=self.address,
            total=Decimal("30.00"),
            currency="EUR",
            payment_status="SUCCESS",
            payment_channel="STRIPE",
            fulfillment_status="TO_PREPARE",
        )
        LigneCommande.objects.create(
            commande=self.order,
            produit=self.product,
            quantite=1,
            prix_unitaire=self.product.prix,
        )

    def test_transition_service_enforces_ordered_paid_workflow(self):
        transition_order_fulfillment(self.order.pk, "PREPARING")
        shipped = transition_order_fulfillment(
            self.order.pk,
            "SHIPPED",
            carrier="  DHL  ",
            tracking_number="  TRACK-123  ",
        )
        delivered = transition_order_fulfillment(self.order.pk, "DELIVERED")

        self.assertEqual(shipped.carrier, "DHL")
        self.assertEqual(shipped.tracking_number, "TRACK-123")
        self.assertIsNotNone(shipped.shipped_at)
        self.assertEqual(delivered.fulfillment_status, "DELIVERED")
        self.assertIsNotNone(delivered.delivered_at)
        self.assertEqual(delivered.payment_status, "SUCCESS")

    def test_unpaid_or_skipped_transition_is_rejected_without_mutation(self):
        with self.assertRaises(InvalidFulfillmentTransition):
            transition_order_fulfillment(self.order.pk, "SHIPPED")

        Commande.objects.filter(pk=self.order.pk).update(payment_status="FAILED")
        with self.assertRaises(PaymentNotConfirmed):
            transition_order_fulfillment(self.order.pk, "PREPARING")

        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, "TO_PREPARE")
        self.assertEqual(self.order.payment_status, "FAILED")
        self.assertIsNone(self.order.shipped_at)

    def test_shipping_requires_complete_bounded_details(self):
        transition_order_fulfillment(self.order.pk, "PREPARING")

        for carrier, tracking_number in (
            ("", "TRACK-123"),
            ("DHL", ""),
            ("D" * 101, "TRACK-123"),
            ("DHL", "T" * 151),
        ):
            with self.subTest(
                carrier_length=len(carrier),
                tracking_length=len(tracking_number),
            ):
                with self.assertRaises(ShippingDetailsInvalid):
                    transition_order_fulfillment(
                        self.order.pk,
                        "SHIPPED",
                        carrier=carrier,
                        tracking_number=tracking_number,
                    )

        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, "PREPARING")
        self.assertEqual(self.order.carrier, "")
        self.assertEqual(self.order.tracking_number, "")

    def test_delivery_rejects_missing_shipping_details(self):
        Commande.objects.filter(pk=self.order.pk).update(
            fulfillment_status="SHIPPED",
            carrier="DHL",
            tracking_number="",
        )

        with self.assertRaises(ShippingDetailsInvalid):
            transition_order_fulfillment(self.order.pk, "DELIVERED")

        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, "SHIPPED")
        self.assertIsNone(self.order.delivered_at)

    def test_transition_and_tracking_updates_lock_the_order(self):
        real_select_for_update = Commande.objects.select_for_update
        with patch.object(
            Commande.objects,
            "select_for_update",
            wraps=real_select_for_update,
        ) as lock:
            transition_order_fulfillment(self.order.pk, "PREPARING")
        lock.assert_called_once_with()

        Commande.objects.filter(pk=self.order.pk).update(
            fulfillment_status="SHIPPED",
            carrier="DHL",
            tracking_number="OLD",
        )
        with patch.object(
            Commande.objects,
            "select_for_update",
            wraps=real_select_for_update,
        ) as lock:
            update_order_shipping_details(
                self.order.pk,
                carrier="UPS",
                tracking_number="NEW",
            )
        lock.assert_called_once_with()

    def test_tracking_edit_rechecks_payment_and_fulfillment_state(self):
        for payment_status, fulfillment_status, expected_exception in (
            ("FAILED", "SHIPPED", PaymentNotConfirmed),
            ("SUCCESS", "PREPARING", ShippingDetailsNotEditable),
        ):
            with self.subTest(
                payment_status=payment_status,
                fulfillment_status=fulfillment_status,
            ):
                Commande.objects.filter(pk=self.order.pk).update(
                    payment_status=payment_status,
                    fulfillment_status=fulfillment_status,
                    carrier="DHL",
                    tracking_number="ORIGINAL",
                )
                with self.assertRaises(expected_exception):
                    update_order_shipping_details(
                        self.order.pk,
                        carrier="UPS",
                        tracking_number="REPLACED",
                    )
                self.order.refresh_from_db()
                self.assertEqual(self.order.carrier, "DHL")
                self.assertEqual(self.order.tracking_number, "ORIGINAL")

    def test_successful_transition_schedules_one_notification_after_commit(self):
        transition_order_fulfillment(self.order.pk, "PREPARING")

        with patch(
            "shop.signals.send_fulfillment_notification"
        ) as notify, self.captureOnCommitCallbacks(execute=True):
            transition_order_fulfillment(
                self.order.pk,
                "SHIPPED",
                carrier="DHL",
                tracking_number="TRACK-123",
            )

        notify.assert_called_once()
        notified_order, notified_status = notify.call_args.args
        self.assertEqual(notified_order.pk, self.order.pk)
        self.assertEqual(notified_status, "SHIPPED")


class FulfillmentViewsAndNotificationSecurityTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            email="fulfillment-staff@example.test",
            password="test-password",
            is_staff=True,
        )
        self.customer = user_model.objects.create_user(
            email="fulfillment-view-customer@example.test",
            password="test-password",
        )
        self.order = Commande.objects.create(
            client=self.customer,
            total=Decimal("10.00"),
            payment_status="SUCCESS",
            payment_channel="STRIPE",
            fulfillment_status="SHIPPED",
            carrier="DHL",
            tracking_number="ORIGINAL",
        )

    def test_shipping_edit_is_staff_only_and_preserves_protected_statuses(self):
        url = reverse("shop:commande_expedition_modifier", args=[self.order.pk])
        self.client.force_login(self.customer)
        self.assertEqual(self.client.post(url, {}).status_code, 302)

        self.client.force_login(self.staff)
        response = self.client.post(
            url,
            {"carrier": "  UPS  ", "tracking_number": "  SAFE-456  "},
        )

        self.assertRedirects(
            response,
            reverse("shop:commande_gestion_detail", args=[self.order.pk]),
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.carrier, "UPS")
        self.assertEqual(self.order.tracking_number, "SAFE-456")
        self.assertEqual(self.order.payment_status, "SUCCESS")
        self.assertEqual(self.order.fulfillment_status, "SHIPPED")

    def test_admin_cannot_bypass_payment_or_fulfillment_workflows(self):
        model_admin = admin.site._registry[Commande]
        self.assertIsInstance(model_admin, CommandeAdmin)
        self.assertTrue(
            {
                "payment_status",
                "payment_channel",
                "transaction_id",
                "fulfillment_status",
                "carrier",
                "tracking_number",
                "shipped_at",
                "delivered_at",
            }.issubset(set(model_admin.readonly_fields))
        )

    @override_settings(DEFAULT_FROM_EMAIL="shop@example.test")
    def test_email_failure_logs_no_recipient_tracking_or_provider_detail(self):
        sensitive_detail = (
            "smtp-secret fulfillment-view-customer@example.test ORIGINAL"
        )
        with patch(
            "shop.shipping.EmailMultiAlternatives.send",
            side_effect=RuntimeError(sensitive_detail),
        ), self.assertLogs("shop.shipping", level="WARNING") as logs:
            sent = send_fulfillment_notification(self.order, "SHIPPED")

        self.assertFalse(sent)
        self.assertEqual(
            logs.output,
            [
                "WARNING:shop.shipping:"
                "operation=fulfillment_notification "
                f"exception_type=RuntimeError order_id={self.order.pk}"
            ],
        )
        rendered_logs = "\n".join(logs.output)
        self.assertNotIn(sensitive_detail, rendered_logs)
        self.assertNotIn(self.customer.email, rendered_logs)
        self.assertNotIn(self.order.tracking_number, rendered_logs)
