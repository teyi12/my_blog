from io import BytesIO
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import translation
from django.utils import timezone

from shop.models import Commande, LigneCommande, Produit


class CustomerOrderHistoryTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.customer = user_model.objects.create_user(
            email="customer-orders@example.com",
            password="test-password",
            first_name="Teyi",
            last_name="Lawson",
        )
        self.other_customer = user_model.objects.create_user(
            email="other-customer@example.com",
            password="test-password",
        )
        self.product = Produit.objects.create(
            nom="Pantalon client",
            slug="pantalon-client-orders",
            prix=Decimal("95.00"),
        )
        self.order = Commande.objects.create(
            client=self.customer,
            total=Decimal("95.00"),
            currency="EUR",
            payment_status="SUCCESS",
            payment_channel="STRIPE",
            fulfillment_status="DELIVERED",
            carrier="DHL",
            tracking_number="TEST-71-2026",
            shipped_at=timezone.now(),
            delivered_at=timezone.now(),
        )
        LigneCommande.objects.create(
            commande=self.order,
            produit=self.product,
            quantite=1,
            prix_unitaire=Decimal("95.00"),
        )
        self.digital_product = Produit.objects.create(
            nom="Guide numérique client",
            slug="guide-numerique-client-orders",
            prix=Decimal("15.00"),
            fichier="produits/fichiers/guide-client.pdf",
        )
        self.digital_line = LigneCommande.objects.create(
            commande=self.order,
            produit=self.digital_product,
            quantite=1,
            prix_unitaire=Decimal("15.00"),
        )
        self.other_order = Commande.objects.create(
            client=self.other_customer,
            total=Decimal("25.00"),
            currency="EUR",
            payment_status="SUCCESS",
            fulfillment_status="TO_PREPARE",
        )
        self.other_line = LigneCommande.objects.create(
            commande=self.other_order,
            produit=self.digital_product,
            quantite=1,
            prix_unitaire=Decimal("15.00"),
        )

    def test_order_history_requires_login(self):
        response = self.client.get(reverse("shop:mes_commandes"))
        self.assertEqual(response.status_code, 302)

    def test_customer_sees_only_own_orders(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("shop:mes_commandes"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Commande #{self.order.pk}")
        self.assertNotContains(response, f"Commande #{self.other_order.pk}")
        self.assertContains(response, "Livrée")
        self.assertContains(response, "TEST-71-2026")

    def test_history_contains_every_payment_status(self):
        for index, status in enumerate(
            ("PENDING", "PROCESSING", "FAILED", "CANCELED"),
            start=1,
        ):
            Commande.objects.create(
                client=self.customer,
                total=Decimal(index),
                payment_status=status,
            )
        self.client.force_login(self.customer)

        response = self.client.get(reverse("shop:mes_commandes"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {order.payment_status for order in response.context["commandes"]},
            {"PENDING", "PROCESSING", "SUCCESS", "FAILED", "CANCELED"},
        )

    def test_history_is_paginated_ten_orders_per_page(self):
        for index in range(11):
            Commande.objects.create(
                client=self.customer,
                total=Decimal(index + 1),
                payment_status="PENDING",
            )
        self.client.force_login(self.customer)

        first_page = self.client.get(reverse("shop:mes_commandes"))
        second_page = self.client.get(reverse("shop:mes_commandes"), {"page": 2})

        self.assertEqual(len(first_page.context["commandes"]), 10)
        self.assertEqual(len(second_page.context["commandes"]), 2)
        first_page_ids = [order.pk for order in first_page.context["commandes"]]
        self.assertEqual(first_page_ids, sorted(first_page_ids, reverse=True))

    def test_customer_can_view_own_order_detail(self):
        self.client.force_login(self.customer)
        response = self.client.get(
            reverse("shop:ma_commande_detail", args=[self.order.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pantalon client")
        self.assertContains(response, "DHL")
        self.assertContains(response, "TEST-71-2026")
        self.assertContains(response, "Suivi de votre commande")
        self.assertContains(response, "Télécharger le fichier")
        self.assertNotContains(response, self.digital_product.fichier.name)

    def test_customer_cannot_view_another_customers_order(self):
        self.client.force_login(self.customer)
        response = self.client.get(
            reverse("shop:ma_commande_detail", args=[self.other_order.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_customer_routes_accept_get_only(self):
        self.client.force_login(self.customer)
        download_url = reverse(
            "shop:telecharger_fichier_commande",
            args=[self.order.pk, self.digital_line.pk],
        )

        self.assertEqual(
            self.client.post(reverse("shop:mes_commandes")).status_code,
            405,
        )
        self.assertEqual(
            self.client.post(
                reverse("shop:ma_commande_detail", args=[self.order.pk])
            ).status_code,
            405,
        )
        self.assertEqual(self.client.post(download_url).status_code, 405)

    def test_download_requires_login(self):
        download_url = reverse(
            "shop:telecharger_fichier_commande",
            args=[self.order.pk, self.digital_line.pk],
        )

        response = self.client.get(download_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_paid_customer_can_download_owned_digital_file(self):
        self.client.force_login(self.customer)
        download_url = reverse(
            "shop:telecharger_fichier_commande",
            args=[self.order.pk, self.digital_line.pk],
        )
        payload = b"paid digital purchase"

        with patch.object(
            self.digital_product.fichier.storage,
            "open",
            return_value=BytesIO(payload),
        ) as storage_open:
            response = self.client.get(download_url)
            body = b"".join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body, payload)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("guide-client.pdf", response["Content-Disposition"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        storage_open.assert_called_once_with(
            self.digital_product.fichier.name,
            "rb",
        )

    def test_unconfirmed_payments_cannot_download(self):
        self.client.force_login(self.customer)
        download_url = reverse(
            "shop:telecharger_fichier_commande",
            args=[self.order.pk, self.digital_line.pk],
        )

        for status in ("PENDING", "PROCESSING", "FAILED", "CANCELED"):
            with self.subTest(status=status):
                self.order.payment_status = status
                self.order.save(update_fields=["payment_status"])
                with patch.object(
                    self.digital_product.fichier.storage,
                    "open",
                ) as storage_open:
                    response = self.client.get(download_url)
                self.assertEqual(response.status_code, 404)
                storage_open.assert_not_called()

        detail = self.client.get(
            reverse("shop:ma_commande_detail", args=[self.order.pk])
        )
        self.assertContains(detail, "Disponible après confirmation du paiement.")
        self.assertNotContains(detail, "Télécharger le fichier")

    def test_download_rejects_another_customer_and_mismatched_line(self):
        self.client.force_login(self.customer)
        other_download = reverse(
            "shop:telecharger_fichier_commande",
            args=[self.other_order.pk, self.other_line.pk],
        )
        mismatched_download = reverse(
            "shop:telecharger_fichier_commande",
            args=[self.order.pk, self.other_line.pk],
        )

        with patch.object(
            self.digital_product.fichier.storage,
            "open",
        ) as storage_open:
            self.assertEqual(self.client.get(other_download).status_code, 404)
            self.assertEqual(self.client.get(mismatched_download).status_code, 404)
        storage_open.assert_not_called()

    def test_download_rejects_line_without_file(self):
        self.client.force_login(self.customer)
        physical_line = self.order.lignes.get(produit=self.product)
        download_url = reverse(
            "shop:telecharger_fichier_commande",
            args=[self.order.pk, physical_line.pk],
        )

        response = self.client.get(download_url)

        self.assertEqual(response.status_code, 404)

    def test_storage_failure_is_controlled_and_logs_no_provider_message(self):
        self.client.force_login(self.customer)
        download_url = reverse(
            "shop:telecharger_fichier_commande",
            args=[self.order.pk, self.digital_line.pk],
        )
        provider_detail = "cloud provider private response and credentials"

        with self.assertLogs("shop.customer_views", level="WARNING") as logs:
            with patch.object(
                self.digital_product.fichier.storage,
                "open",
                side_effect=OSError(provider_detail),
            ):
                response = self.client.get(download_url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "temporairement indisponible")
        log_output = "\n".join(logs.output)
        self.assertIn("exception_type=OSError", log_output)
        self.assertNotIn(provider_detail, log_output)
        self.assertNotIn(self.digital_product.fichier.name, log_output)
        self.assertNotIn(self.customer.email, log_output)

    def test_non_storage_exception_is_not_hidden(self):
        self.client.force_login(self.customer)
        download_url = reverse(
            "shop:telecharger_fichier_commande",
            args=[self.order.pk, self.digital_line.pk],
        )

        with patch.object(
            self.digital_product.fichier.storage,
            "open",
            side_effect=RuntimeError("programming error"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.get(download_url)

    def test_download_labels_are_translated(self):
        self.client.force_login(self.customer)

        with translation.override("en"):
            english = self.client.get(
                reverse("shop:ma_commande_detail", args=[self.order.pk])
            )
        with translation.override("de"):
            german = self.client.get(
                reverse("shop:ma_commande_detail", args=[self.order.pk])
            )

        self.assertContains(english, "Download file")
        self.assertContains(german, "Datei herunterladen")
