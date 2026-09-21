from decimal import Decimal
from importlib import import_module
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation
from modeltranslation.admin import TranslationTabularInline
from modeltranslation.translator import translator

from .admin import ProduitImageInline
from .models import Produit, ProduitImage


class ProductImageGalleryModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Produit.objects.create(
            nom_fr="Produit principal français",
            nom_de="Deutsches Hauptprodukt",
            nom_en="English main product",
            slug="produit-galerie",
            prix=Decimal("19.90"),
            image="produits/principale.jpg",
        )

    def setUp(self):
        translation.activate("fr")
        self.addCleanup(translation.activate, "fr")

    def test_multiple_secondary_images_use_explicit_relation_and_same_storage(self):
        first = ProduitImage.objects.create(
            produit=self.product,
            image="produits/galerie/une.jpg",
        )
        second = ProduitImage.objects.create(
            produit=self.product,
            image="produits/galerie/deux.jpg",
        )

        self.assertEqual(
            list(self.product.images_secondaires.values_list("pk", flat=True)),
            [first.pk, second.pk],
        )
        self.assertIs(
            Produit._meta.get_field("image").storage,
            ProduitImage._meta.get_field("image").storage,
        )

    def test_order_is_deterministic_when_positions_are_equal(self):
        later_position = ProduitImage.objects.create(
            produit=self.product,
            image="produits/galerie/trois.jpg",
            ordre=3,
        )
        first_equal = ProduitImage.objects.create(
            produit=self.product,
            image="produits/galerie/une.jpg",
            ordre=1,
        )
        second_equal = ProduitImage.objects.create(
            produit=self.product,
            image="produits/galerie/deux.jpg",
            ordre=1,
        )

        self.assertEqual(
            [image.pk for image in self.product.get_public_secondary_images()],
            [first_equal.pk, second_equal.pk, later_position.pk],
        )

    def test_legacy_main_image_remains_primary_and_empty_gallery_is_supported(self):
        self.assertFalse(self.product.images_secondaires.exists())
        self.assertEqual(
            self.product.get_display_image().name,
            "produits/principale.jpg",
        )

    def test_product_without_main_image_falls_back_to_first_secondary_image(self):
        product = Produit.objects.create(
            nom="Produit sans image principale",
            slug="produit-sans-image-principale",
            prix=Decimal("12.00"),
            image=None,
        )
        second = ProduitImage.objects.create(
            produit=product,
            image="produits/galerie/seconde.jpg",
            ordre=2,
        )
        first = ProduitImage.objects.create(
            produit=product,
            image="produits/galerie/premiere.jpg",
            ordre=1,
        )

        self.assertEqual(product.get_display_image().name, first.image.name)
        self.assertNotEqual(product.get_display_image().name, second.image.name)

    def test_localized_alt_uses_target_then_french_then_localized_product_name(self):
        translated = ProduitImage.objects.create(
            produit=self.product,
            image="produits/galerie/traduite.jpg",
            texte_alternatif_fr="Vue française",
            texte_alternatif_de="Deutsche Ansicht",
            texte_alternatif_en="English view",
        )
        french_fallback = ProduitImage.objects.create(
            produit=self.product,
            image="produits/galerie/repli.jpg",
            texte_alternatif_fr="Vue française de repli",
            texte_alternatif_de="   ",
            texte_alternatif_en="",
        )
        name_fallback = ProduitImage.objects.create(
            produit=self.product,
            image="produits/galerie/nom.jpg",
            texte_alternatif_fr="   ",
            texte_alternatif_de="  ",
            texte_alternatif_en="\t",
        )

        for language, expected in {
            "fr": "Vue française",
            "de": "Deutsche Ansicht",
            "en": "English view",
        }.items():
            with self.subTest(language=language), translation.override(language):
                self.assertEqual(translated.localized_alt_text, expected)

        for language in ("de", "en"):
            with self.subTest(french_fallback=language):
                self.assertEqual(
                    french_fallback.localized_alt_text_for(language),
                    "Vue française de repli",
                )

        self.assertEqual(
            name_fallback.localized_alt_text_for("de"),
            "Deutsches Hauptprodukt",
        )
        self.assertEqual(
            name_fallback.localized_alt_text_for("en"),
            "English main product",
        )

    def test_alt_can_be_empty_only_when_no_useful_text_exists(self):
        product = Produit.objects.create(
            nom="",
            nom_fr="",
            nom_de="",
            nom_en="",
            slug="produit-sans-texte",
            prix=Decimal("5.00"),
        )
        image = ProduitImage.objects.create(
            produit=product,
            image="produits/galerie/sans-texte.jpg",
            texte_alternatif_fr=" ",
            texte_alternatif_de="\t",
            texte_alternatif_en="\n",
        )

        self.assertEqual(image.localized_alt_text_for("de"), "")

    def test_product_delete_cascades_rows_without_deleting_storage_objects(self):
        image = ProduitImage.objects.create(
            produit=self.product,
            image="produits/galerie/conservee.jpg",
        )
        storage = ProduitImage._meta.get_field("image").storage

        with patch.object(storage, "delete") as storage_delete:
            self.product.delete()

        self.assertFalse(ProduitImage.objects.filter(pk=image.pk).exists())
        storage_delete.assert_not_called()

    def test_row_delete_does_not_delete_storage_object(self):
        image = ProduitImage.objects.create(
            produit=self.product,
            image="produits/galerie/partagee.jpg",
        )
        storage = ProduitImage._meta.get_field("image").storage

        with patch.object(storage, "delete") as storage_delete:
            image.delete()

        storage_delete.assert_not_called()

    def test_gallery_does_not_change_digital_or_physical_product_rules(self):
        digital = Produit.objects.create(
            nom="Produit numérique",
            slug="produit-numerique-galerie",
            prix=Decimal("8.00"),
            fichier="produits/fichiers/guide.pdf",
            stock=0,
        )
        physical = Produit.objects.create(
            nom="Produit physique",
            slug="produit-physique-galerie",
            prix=Decimal("15.00"),
            stock=2,
        )
        for product in (digital, physical):
            ProduitImage.objects.create(
                produit=product,
                image=f"produits/galerie/{product.slug}.jpg",
            )

        self.assertTrue(digital.est_numerique)
        self.assertFalse(digital.stock_est_gere)
        self.assertTrue(digital.est_disponible)
        self.assertFalse(physical.est_numerique)
        self.assertTrue(physical.stock_est_gere)
        self.assertTrue(physical.est_disponible)


class ProductImageGalleryQueryTests(TestCase):
    def test_explicit_prefetch_prevents_gallery_n_plus_one(self):
        for product_index in range(3):
            product = Produit.objects.create(
                nom=f"Produit {product_index}",
                slug=f"produit-prefetch-{product_index}",
                prix=Decimal("10.00"),
            )
            for image_index in range(2):
                ProduitImage.objects.create(
                    produit=product,
                    image=f"produits/galerie/{product_index}-{image_index}.jpg",
                    ordre=image_index,
                )

        with self.assertNumQueries(2):
            products = list(Produit.objects.order_by("pk").with_secondary_images())
            names = [
                [image.image.name for image in product.get_public_secondary_images()]
                for product in products
            ]

        self.assertEqual(len(names), 3)
        self.assertTrue(all(len(product_names) == 2 for product_names in names))

    def test_public_list_keeps_main_image_fast_path_without_gallery_query(self):
        product = Produit.objects.create(
            nom="Produit chemin rapide",
            slug="produit-chemin-rapide",
            prix=Decimal("10.00"),
            image="produits/principale-rapide.jpg",
        )
        ProduitImage.objects.create(
            produit=product,
            image="produits/galerie/non-chargee.jpg",
        )

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("shop:liste"))

        self.assertEqual(response.status_code, 200)
        gallery_table = ProduitImage._meta.db_table
        self.assertFalse(
            any(gallery_table in query["sql"] for query in captured.captured_queries)
        )


class ProductImageGalleryAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_superuser(
            email="gallery-admin@example.test",
            password="test-password",
        )
        cls.regular_user = User.objects.create_user(
            email="gallery-user@example.test",
            password="test-password",
        )
        cls.product = Produit.objects.create(
            nom="Produit administré",
            slug="produit-admin-galerie",
            prix=Decimal("25.00"),
        )
        cls.image = ProduitImage.objects.create(
            produit=cls.product,
            image="produits/galerie/admin.jpg",
            texte_alternatif_fr="Vue administrée",
            ordre=4,
        )

    def test_admin_uses_translated_inline_with_only_useful_fields(self):
        product_admin = admin.site._registry[Produit]
        self.assertIn(ProduitImageInline, product_admin.inlines)
        self.assertTrue(issubclass(ProduitImageInline, TranslationTabularInline))
        self.assertEqual(
            ProduitImageInline.fields,
            (
                "image",
                "image_link",
                "ordre",
                "texte_alternatif_fr",
                "texte_alternatif_de",
                "texte_alternatif_en",
            ),
        )
        options = translator.get_options_for_model(ProduitImage)
        self.assertEqual(set(options.fields), {"texte_alternatif"})

    def test_staff_can_edit_inline_and_non_staff_is_refused(self):
        url = reverse("admin:shop_produit_change", args=[self.product.pk])
        self.client.force_login(self.staff)
        staff_response = self.client.get(url)
        self.assertEqual(staff_response.status_code, 200)
        for field_name in (
            "image",
            "ordre",
            "texte_alternatif_fr",
            "texte_alternatif_de",
            "texte_alternatif_en",
        ):
            self.assertContains(
                staff_response,
                f'name="images_secondaires-0-{field_name}"',
            )
        self.assertContains(staff_response, 'rel="noopener noreferrer"')

        self.client.force_login(self.regular_user)
        regular_response = self.client.get(url)
        self.assertEqual(regular_response.status_code, 302)


class ProductImageGalleryMigrationTests(TransactionTestCase):
    migrate_from = [("shop", "0024_order_fulfillment_integrity")]
    migrate_to = [("shop", "0025_produitimage")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldProduct = old_apps.get_model("shop", "Produit")
        self.product_id = OldProduct.objects.create(
            nom="Produit historique galerie",
            slug="produit-historique-galerie",
            prix=Decimal("11.00"),
            image="produits/historique-galerie.jpg",
        ).pk

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_migration_is_importable_additive_and_reversible(self):
        migration_module = import_module("shop.migrations.0025_produitimage")
        self.assertTrue(migration_module.Migration.operations)

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        Product = apps.get_model("shop", "Produit")
        ProductImage = apps.get_model("shop", "ProduitImage")

        product = Product.objects.get(pk=self.product_id)
        self.assertEqual(product.image.name, "produits/historique-galerie.jpg")
        self.assertEqual(ProductImage.objects.count(), 0)
        ProductImage.objects.create(
            produit_id=self.product_id,
            image="produits/galerie/migration.jpg",
            ordre=1,
        )

        MigrationExecutor(connection).migrate(self.migrate_from)
        reverse_apps = MigrationExecutor(connection).loader.project_state(
            self.migrate_from
        ).apps
        ReverseProduct = reverse_apps.get_model("shop", "Produit")
        self.assertEqual(
            ReverseProduct.objects.get(pk=self.product_id).image.name,
            "produits/historique-galerie.jpg",
        )
