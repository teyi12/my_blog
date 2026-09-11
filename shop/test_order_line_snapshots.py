from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from shop.models import (
    Commande,
    LigneCommande,
    Produit,
    product_file_storage,
)


class OrderLineSnapshotTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.customer = user_model.objects.create_user(
            email="snapshot-customer@example.com",
            password="test-password",
        )
        self.staff = user_model.objects.create_user(
            email="snapshot-staff@example.com",
            password="test-password",
            is_staff=True,
        )
        self.storage_name = "produits/fichiers/catalogue-prive/guide-original.pdf"
        self.product = Produit.objects.create(
            nom="Guide historique",
            slug="guide-historique",
            prix=Decimal("19.00"),
            fichier=self.storage_name,
        )
        self.order = Commande.objects.create(
            client=self.customer,
            total=Decimal("19.00"),
            payment_status="SUCCESS",
        )
        self.line = LigneCommande.objects.create(
            commande=self.order,
            produit=self.product,
            quantite=1,
            prix_unitaire=Decimal("19.00"),
        )

    def test_normal_creation_populates_immutable_snapshots(self):
        self.assertEqual(self.line.nom_produit_snapshot, "Guide historique")
        self.assertEqual(
            self.line.fichier_nom_stockage_snapshot,
            self.storage_name,
        )
        self.assertEqual(
            self.line.fichier_nom_telechargement_snapshot,
            "guide-original.pdf",
        )

        self.product.nom = "Guide renommé"
        self.product.fichier = "produits/fichiers/guide-remplace.pdf"
        self.product.save()
        self.line.nom_produit_snapshot = "Valeur écrasée"
        self.line.fichier_nom_stockage_snapshot = "secret/remplace.pdf"
        self.line.fichier_nom_telechargement_snapshot = "remplace.pdf"
        self.line.quantite = 2
        self.line.save()
        self.line.refresh_from_db()

        self.assertEqual(self.line.nom_produit_snapshot, "Guide historique")
        self.assertEqual(
            self.line.fichier_nom_stockage_snapshot,
            self.storage_name,
        )
        self.assertEqual(
            self.line.fichier_nom_telechargement_snapshot,
            "guide-original.pdf",
        )
        self.assertEqual(self.line.quantite, 2)

    def test_normal_creation_uses_order_language_not_active_language(self):
        localized_product = Produit.objects.create(
            nom_fr="Manuel français",
            nom_de="Deutsches Handbuch",
            nom_en="English handbook",
            slug="manuel-multilingue-snapshot",
            prix=Decimal("8.00"),
        )
        cases = (
            ("de", "fr", "Deutsches Handbuch"),
            ("en", "de", "English handbook"),
        )

        for order_language, active_language, expected_name in cases:
            with self.subTest(order_language=order_language):
                order = Commande.objects.create(
                    client=self.customer,
                    total=Decimal("8.00"),
                    language_code=order_language,
                )
                with translation.override(active_language):
                    line = LigneCommande.objects.create(
                        commande=order,
                        produit=localized_product,
                        quantite=1,
                        prix_unitaire=Decimal("8.00"),
                    )

                self.assertEqual(line.nom_produit_snapshot, expected_name)

        fallback_product = Produit.objects.create(
            nom_fr="Nom français de repli",
            nom_de="",
            nom_en="",
            slug="nom-snapshot-repli",
            prix=Decimal("4.00"),
        )
        fallback_order = Commande.objects.create(
            client=self.customer,
            total=Decimal("4.00"),
            language_code="de",
        )
        with translation.override("en"):
            fallback_line = LigneCommande.objects.create(
                commande=fallback_order,
                produit=fallback_product,
                quantite=1,
                prix_unitaire=Decimal("4.00"),
            )
        self.assertEqual(
            fallback_line.nom_produit_snapshot,
            "Nom français de repli",
        )

    def test_empty_file_snapshots_stay_empty_after_product_gains_file(self):
        physical_product = Produit.objects.create(
            nom="Livre physique",
            slug="livre-physique-snapshot-vide",
            prix=Decimal("12.00"),
        )
        physical_line = LigneCommande.objects.create(
            commande=self.order,
            produit=physical_product,
            quantite=1,
            prix_unitaire=Decimal("12.00"),
        )
        self.assertEqual(physical_line.fichier_nom_stockage_snapshot, "")
        self.assertEqual(
            physical_line.fichier_nom_telechargement_snapshot,
            "",
        )

        physical_product.fichier = "produits/fichiers/ajoute-plus-tard.pdf"
        physical_product.save(update_fields=["fichier"])
        physical_line.fichier_nom_stockage_snapshot = physical_product.fichier.name
        physical_line.fichier_nom_telechargement_snapshot = "ajoute-plus-tard.pdf"
        physical_line.quantite = 2
        physical_line.save()
        physical_line.refresh_from_db()

        self.assertEqual(physical_line.fichier_nom_stockage_snapshot, "")
        self.assertEqual(
            physical_line.fichier_nom_telechargement_snapshot,
            "",
        )
        self.assertEqual(physical_line.quantite, 2)
        self.client.force_login(self.customer)
        with patch.object(product_file_storage(), "open") as storage_open:
            response = self.client.get(
                reverse(
                    "shop:telecharger_fichier_commande",
                    args=[self.order.pk, physical_line.pk],
                )
            )
        self.assertEqual(response.status_code, 404)
        storage_open.assert_not_called()

    def test_historical_pages_use_snapshot_and_survive_product_deletion(self):
        original_file_url = self.product.fichier.url
        self.product.nom = "Guide renommé"
        self.product.fichier = "produits/fichiers/nouveau-guide-secret.pdf"
        self.product.save()
        replacement_storage_name = self.product.fichier.name
        replacement_file_url = self.product.fichier.url

        self.client.force_login(self.customer)
        history = self.client.get(reverse("shop:mes_commandes"))
        customer_detail = self.client.get(
            reverse("shop:ma_commande_detail", args=[self.order.pk])
        )
        self.client.force_login(self.staff)
        staff_detail = self.client.get(
            reverse("shop:commande_gestion_detail", args=[self.order.pk])
        )

        for response in (history, customer_detail, staff_detail):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Guide historique")
            self.assertNotContains(response, "Guide renommé")
            self.assertNotContains(response, self.storage_name)
            self.assertNotContains(response, replacement_storage_name)
            self.assertNotContains(response, original_file_url)
            self.assertNotContains(response, replacement_file_url)

        product_pk = self.product.pk
        self.product.delete()
        self.line.refresh_from_db()

        self.assertIsNone(self.line.produit)
        self.assertTrue(Commande.objects.filter(pk=self.order.pk).exists())
        self.assertFalse(Produit.objects.filter(pk=product_pk).exists())
        self.client.force_login(self.customer)
        customer_detail = self.client.get(
            reverse("shop:ma_commande_detail", args=[self.order.pk])
        )
        self.client.force_login(self.staff)
        staff_detail = self.client.get(
            reverse("shop:commande_gestion_detail", args=[self.order.pk])
        )
        for response in (customer_detail, staff_detail):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Guide historique")

    def test_paid_download_uses_snapshot_after_product_change_and_deletion(self):
        self.product.fichier = "produits/fichiers/nouveau-guide.pdf"
        self.product.save(update_fields=["fichier"])
        self.product.delete()
        payload = b"historical digital purchase"
        self.client.force_login(self.customer)

        with patch.object(
            product_file_storage(),
            "open",
            return_value=BytesIO(payload),
        ) as storage_open:
            response = self.client.get(
                reverse(
                    "shop:telecharger_fichier_commande",
                    args=[self.order.pk, self.line.pk],
                )
            )
            body = b"".join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body, payload)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("guide-original.pdf", response["Content-Disposition"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        storage_open.assert_called_once_with(self.storage_name, "rb")

    def test_unpaid_snapshot_download_remains_blocked(self):
        self.order.payment_status = "PENDING"
        self.order.save(update_fields=["payment_status"])
        self.client.force_login(self.customer)

        with patch.object(product_file_storage(), "open") as storage_open:
            response = self.client.get(
                reverse(
                    "shop:telecharger_fichier_commande",
                    args=[self.order.pk, self.line.pk],
                )
            )

        self.assertEqual(response.status_code, 404)
        storage_open.assert_not_called()

    def test_exceptional_line_without_product_or_snapshot_has_safe_fallback(self):
        fallback_line = LigneCommande.objects.create(
            commande=self.order,
            produit=None,
            quantite=1,
            prix_unitaire=Decimal("3.00"),
        )
        self.assertEqual(fallback_line.nom_produit_affiche, "Produit indisponible")
        self.assertFalse(fallback_line.a_fichier_numerique)

        self.client.force_login(self.customer)
        response = self.client.get(
            reverse("shop:ma_commande_detail", args=[self.order.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Produit indisponible")
