import json
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from payments.models import Adresse, Payment
from payments.views import _confirm_payment_once
from shop.models import Commande, LigneCommande, OrderReceipt, Produit
from shop.receipts import (
    OrderReceiptPDFError,
    ensure_order_receipt,
    receipt_pdf_labels,
    receipt_snapshot_defaults,
    render_order_receipt_pdf,
)
from shop.services import finalize_paid_order


class OrderReceiptFixtureMixin:
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="receipt-customer@example.test",
            password="test-password",
            first_name="Élodie",
            last_name="Müller",
        )
        self.other_user = get_user_model().objects.create_user(
            email="other-receipt-customer@example.test",
            password="test-password",
        )
        self.address = Adresse.objects.create(
            utilisateur=self.user,
            rue="12 rue de l’Été <privée>",
            code_postal="75001",
            ville="München & Paris",
            pays="Deutschland",
            telephone="+49-secret-phone",
        )
        self.product_counter = 0

    def create_order(
        self,
        *,
        status="PROCESSING",
        channel="STRIPE",
        language_code="fr",
        user=None,
        product_name="Édition Übergrößenträger €",
    ):
        self.product_counter += 1
        owner = user or self.user
        product = Produit.objects.create(
            nom_fr=product_name,
            nom_de="Deutsches Handbuch für Größe €",
            nom_en="English handbook – special edition €",
            slug=f"receipt-product-{self.product_counter}",
            prix=Decimal("12.50"),
            fichier="produits/fichiers/private/cloudinary-key.pdf",
        )
        address = self.address if owner == self.user else Adresse.objects.create(
            utilisateur=owner,
            rue="Other street",
            code_postal="10000",
            ville="Other city",
            pays="Other country",
        )
        order = Commande.objects.create(
            client=owner,
            adresse=address,
            total=Decimal("25.00"),
            currency="EUR",
            language_code=language_code,
            payment_status=status,
            payment_channel=channel,
            transaction_id=f"provider-secret-{self.product_counter}",
        )
        line = LigneCommande.objects.create(
            commande=order,
            produit=product,
            quantite=2,
            prix_unitaire=Decimal("12.50"),
        )
        return order, line, product

    def confirm_order(self, *, channel="STRIPE", language_code="fr"):
        order, line, product = self.create_order(
            channel=channel,
            language_code=language_code,
        )
        payment = Payment.objects.create(
            commande=order,
            montant=order.total,
            devise=order.currency,
            transaction_id=order.transaction_id,
            channel=channel,
            status="PROCESSING",
        )
        _confirm_payment_once(
            payment.pk,
            {"provider": "secret-provider-payload", "card": "4242424242424242"},
        )
        order.refresh_from_db()
        payment.refresh_from_db()
        return order, payment, line, product, order.receipt


@override_settings(
    ORDER_RECEIPT_ISSUER_NAME="Teyilawson Test",
    ORDER_RECEIPT_ISSUER_CONTACT="contact@example.test",
)
class OrderReceiptTests(OrderReceiptFixtureMixin, TestCase):
    def test_non_success_orders_never_receive_a_receipt(self):
        for status in ("PENDING", "PROCESSING", "FAILED", "CANCELED"):
            with self.subTest(status=status):
                order, _line, _product = self.create_order(status=status)
                self.assertIsNone(ensure_order_receipt(order))
                self.assertFalse(OrderReceipt.objects.filter(commande=order).exists())

    def test_stripe_and_cinetpay_confirmation_create_safe_snapshots(self):
        for channel in ("STRIPE", "CINETPAY"):
            with self.subTest(channel=channel):
                order, payment, line, _product, receipt = self.confirm_order(
                    channel=channel
                )
                self.assertEqual(order.payment_status, "SUCCESS")
                self.assertEqual(payment.status, "SUCCESS")
                self.assertEqual(receipt.commande, order)
                self.assertEqual(receipt.payment_channel, channel)
                self.assertEqual(receipt.customer_name, "Élodie Müller")
                self.assertEqual(receipt.customer_email, self.user.email)
                self.assertEqual(receipt.address_snapshot["street"], self.address.rue)
                self.assertEqual(
                    receipt.items_snapshot,
                    [
                        {
                            "name": line.nom_produit_snapshot,
                            "quantity": 2,
                            "unit_price": "12.50",
                            "subtotal": "25.00",
                        }
                    ],
                )
                serialized = json.dumps(receipt.items_snapshot)
                self.assertNotIn("fichier", serialized)
                self.assertNotIn("cloudinary", serialized)
                self.assertNotIn("provider", serialized)
                self.assertNotIn("raw_response", serialized)

    def test_redelivery_is_idempotent_and_repairs_a_missing_receipt(self):
        order, payment, _line, _product, receipt = self.confirm_order()
        original_values = (
            receipt.public_id,
            receipt.issued_at,
            receipt.items_snapshot,
        )

        _confirm_payment_once(payment.pk, {"provider": "redelivery"})
        receipt.refresh_from_db()
        self.assertEqual(OrderReceipt.objects.filter(commande=order).count(), 1)
        self.assertEqual(
            (receipt.public_id, receipt.issued_at, receipt.items_snapshot),
            original_values,
        )

        receipt.delete()
        self.assertFalse(OrderReceipt.objects.filter(commande=order).exists())
        _confirm_payment_once(payment.pk, {"provider": "repair"})
        self.assertEqual(OrderReceipt.objects.filter(commande=order).count(), 1)
        repaired = OrderReceipt.objects.get(commande=order)
        self.assertEqual(repaired.issued_at, original_values[1])

    def test_one_to_one_and_save_guard_keep_the_receipt_immutable(self):
        order, _payment, _line, _product, receipt = self.confirm_order()
        original = {
            field: getattr(receipt, field)
            for field in OrderReceipt.IMMUTABLE_FIELDS
        }
        receipt.total = Decimal("1.00")
        receipt.customer_email = "changed@example.test"
        receipt.items_snapshot = []
        receipt.address_snapshot = {}
        receipt.issuer_name = "Changed"
        receipt.save()
        receipt.refresh_from_db()
        for field, value in original.items():
            self.assertEqual(getattr(receipt, field), value)

        with self.assertRaises(IntegrityError), transaction.atomic():
            OrderReceipt.objects.create(
                commande=order,
                **receipt_snapshot_defaults(order),
            )

    def test_receipt_snapshot_survives_profile_address_and_product_changes(self):
        order, _payment, _line, product, receipt = self.confirm_order()
        original_snapshot = {
            "issuer_name": receipt.issuer_name,
            "issuer_contact": receipt.issuer_contact,
            "customer_name": receipt.customer_name,
            "customer_email": receipt.customer_email,
            "address_snapshot": receipt.address_snapshot,
            "items_snapshot": receipt.items_snapshot,
        }

        self.user.first_name = "Changed"
        self.user.last_name = "Person"
        self.user.email = "changed-profile@example.test"
        self.user.save(update_fields=["first_name", "last_name", "email"])
        self.address.delete()
        product.delete()
        receipt.refresh_from_db()

        for field, value in original_snapshot.items():
            self.assertEqual(getattr(receipt, field), value)
        self.assertTrue(render_order_receipt_pdf(receipt).startswith(b"%PDF"))
        order.refresh_from_db()
        self.assertIsNone(order.adresse)

    def test_pdf_uses_historical_language_and_supports_unicode_and_euro(self):
        expected = {
            "fr": ("Reçu de paiement", "Ce reçu confirme le paiement"),
            "de": ("Zahlungsbeleg", "Dieser Beleg bestätigt die Zahlung"),
            "en": ("Payment receipt", "This receipt confirms payment"),
        }
        for language_code, (title, legal_note) in expected.items():
            with self.subTest(language_code=language_code):
                active_language = "en" if language_code != "en" else "de"
                with translation.override(active_language):
                    _order, _payment, _line, _product, receipt = self.confirm_order(
                        language_code=language_code
                    )
                    labels = receipt_pdf_labels(receipt.language_code)
                    pdf_bytes = render_order_receipt_pdf(receipt)
                self.assertEqual(labels["title"], title)
                self.assertIn(legal_note, labels["legal_note"])
                self.assertEqual(receipt.items_snapshot[0]["name"].count("€"), 1)
                self.assertTrue(pdf_bytes.startswith(b"%PDF"))
                self.assertGreater(len(pdf_bytes), 5000)

    def test_many_unicode_lines_generate_a_multipage_pdf(self):
        _order, _payment, _line, _product, receipt = self.confirm_order()
        receipt.items_snapshot = [
            {
                "name": f"Élément Über numéro {number} € <&>",
                "quantity": 1,
                "unit_price": "1.00",
                "subtotal": "1.00",
            }
            for number in range(120)
        ]
        pdf_bytes = render_order_receipt_pdf(receipt)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreaterEqual(pdf_bytes.count(b"/Type /Page"), 3)


@override_settings(
    ORDER_RECEIPT_ISSUER_NAME="Teyilawson Test",
    ORDER_RECEIPT_ISSUER_CONTACT="contact@example.test",
)
class OrderReceiptDownloadTests(OrderReceiptFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.order, self.payment, self.line, self.product, self.receipt = (
            self.confirm_order()
        )
        self.url = reverse(
            "shop:telecharger_recu_commande",
            args=[self.order.pk, self.receipt.public_id],
        )

    def test_download_requires_exact_owner_order_and_receipt_pair(self):
        anonymous_response = self.client.get(self.url)
        self.assertEqual(anonymous_response.status_code, 302)

        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(self.url).status_code, 404)

        self.client.force_login(self.user)
        self.assertEqual(
            self.client.get(
                reverse(
                    "shop:telecharger_recu_commande",
                    args=[self.order.pk, uuid.uuid4()],
                )
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse(
                    "shop:telecharger_recu_commande",
                    args=[self.order.pk + 9999, self.receipt.public_id],
                )
            ).status_code,
            404,
        )
        other_order, _payment, _line, _product, other_receipt = self.confirm_order()
        incoherent_url = reverse(
            "shop:telecharger_recu_commande",
            args=[self.order.pk, other_receipt.public_id],
        )
        self.assertEqual(self.client.get(incoherent_url).status_code, 404)
        self.assertNotEqual(other_order.pk, self.order.pk)

    def test_download_is_get_only_and_blocks_order_no_longer_successful(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(self.url).status_code, 405)
        self.order.payment_status = "FAILED"
        self.order.save(update_fields=["payment_status"])
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_download_returns_valid_pdf_with_safe_headers_and_no_secrets(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(
            response["Content-Security-Policy"],
            "default-src 'none'; sandbox",
        )
        self.assertEqual(
            response["Content-Disposition"],
            f'attachment; filename="recu-commande-{self.order.pk}.pdf"',
        )
        self.assertNotIn(self.user.email, response["Content-Disposition"])
        self.assertNotIn(str(self.receipt.public_id), response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))
        for forbidden in (
            self.order.transaction_id,
            "secret-provider-payload",
            "4242424242424242",
            self.line.fichier_nom_stockage_snapshot,
        ):
            self.assertNotIn(forbidden.encode(), response.content)

    def test_detail_button_exists_only_for_a_paid_order_with_receipt(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("shop:ma_commande_detail", args=[self.order.pk])
        )
        self.assertContains(response, "Télécharger le reçu PDF")
        self.assertContains(response, self.url)
        self.assertNotContains(response, self.order.transaction_id)
        self.assertNotContains(
            response,
            self.line.fichier_nom_stockage_snapshot,
        )

        pending_order, _line, _product = self.create_order(status="PENDING")
        pending_response = self.client.get(
            reverse("shop:ma_commande_detail", args=[pending_order.pk])
        )
        self.assertNotContains(pending_response, "Télécharger le reçu PDF")

    def test_expected_pdf_error_returns_translated_503_with_safe_log(self):
        self.client.force_login(self.user)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "de"
        with translation.override("de"):
            localized_url = reverse(
                "shop:telecharger_recu_commande",
                args=[self.order.pk, self.receipt.public_id],
            )
        with self.assertLogs("shop.customer_views", level="ERROR") as logs:
            with patch(
                "shop.customer_views.render_order_receipt_pdf",
                side_effect=OrderReceiptPDFError(
                    "provider /secret/path customer@example.test"
                ),
            ):
                response = self.client.get(localized_url)

        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "PDF-Beleg", status_code=503)
        log_output = " ".join(logs.output)
        self.assertIn("operation=customer_order_receipt_pdf", log_output)
        self.assertIn("exception_type=OrderReceiptPDFError", log_output)
        self.assertIn(f"order_id={self.order.pk}", log_output)
        self.assertNotIn("provider", log_output)
        self.assertNotIn("/secret/path", log_output)
        self.assertNotIn("customer@example.test", log_output)

    def test_unexpected_runtime_and_database_errors_are_not_masked(self):
        self.client.force_login(self.user)
        for error in (RuntimeError("unexpected"), DatabaseError("database")):
            with self.subTest(error=type(error).__name__):
                with patch(
                    "shop.customer_views.render_order_receipt_pdf",
                    side_effect=error,
                ):
                    with self.assertRaises(type(error)):
                        self.client.get(self.url)
