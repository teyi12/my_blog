from decimal import Decimal
from importlib import import_module

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from payments.models import Payment


class ShopCatalogTranslationMigrationTests(TransactionTestCase):
    migrate_from = [("shop", "0014_cart_integrity_constraints")]
    schema_target = [("shop", "0015_product_category_translations")]
    migrate_to = [("shop", "0016_populate_french_product_category_translations")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        User = old_apps.get_model("accounts", "CustomUser")
        Categorie = old_apps.get_model("shop", "Categorie")
        Produit = old_apps.get_model("shop", "Produit")
        Cart = old_apps.get_model("shop", "Cart")
        CartItem = old_apps.get_model("shop", "CartItem")
        Commande = old_apps.get_model("shop", "Commande")
        LigneCommande = old_apps.get_model("shop", "LigneCommande")

        self.user = User.objects.create(email="catalog-migration@example.com")
        self.category = Categorie.objects.create(
            nom="Catégorie historique",
            slug="categorie-historique",
        )
        self.preserved_category = Categorie.objects.create(
            nom="Catégorie source",
            slug="categorie-source",
        )
        self.product = Produit.objects.create(
            nom="Produit historique",
            description="Description historique exacte.",
            slug="produit-historique-i18n",
            prix=Decimal("37.45"),
            image="produits/historique.jpg",
            fichier="produits/fichiers/historique.pdf",
            categorie=self.category,
            en_vedette=True,
        )
        self.preserved_product = Produit.objects.create(
            nom="Produit source",
            description="Description source.",
            slug="produit-source",
            prix=Decimal("11.00"),
            categorie=self.preserved_category,
        )
        self.cart = Cart.objects.create(user=self.user, actif=True)
        self.cart_item = CartItem.objects.create(
            cart=self.cart,
            produit=self.product,
            quantite=3,
            prix_unitaire=Decimal("37.45"),
        )
        self.order = Commande.objects.create(
            client=self.user,
            source_cart=self.cart,
            total=Decimal("112.35"),
            payment_status="SUCCESS",
            currency="EUR",
        )
        self.order_line = LigneCommande.objects.create(
            commande=self.order,
            produit=self.product,
            source_cart_item=self.cart_item,
            quantite=3,
            prix_unitaire=Decimal("37.45"),
        )
        self.payment = Payment.objects.create(
            commande_id=self.order.pk,
            montant=Decimal("112.35"),
            devise="EUR",
            transaction_id="catalog-migration-payment",
            checkout_url="",
            channel="STRIPE",
            status="SUCCESS",
        )

        executor = MigrationExecutor(connection)
        executor.migrate(self.schema_target)
        schema_apps = executor.loader.project_state(self.schema_target).apps
        schema_apps.get_model("shop", "Categorie").objects.filter(
            pk=self.preserved_category.pk
        ).update(nom_fr="Catégorie française déjà renseignée")
        schema_apps.get_model("shop", "Produit").objects.filter(
            pk=self.preserved_product.pk
        ).update(
            nom_fr="Produit français déjà renseigné",
            description_fr="Description française déjà renseignée.",
        )

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def _migrate_and_get_apps(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        return executor.loader.project_state(self.migrate_to).apps

    def test_migration_copies_legacy_values_without_touching_related_data(self):
        apps = self._migrate_and_get_apps()
        User = apps.get_model("accounts", "CustomUser")
        Categorie = apps.get_model("shop", "Categorie")
        Produit = apps.get_model("shop", "Produit")
        Cart = apps.get_model("shop", "Cart")
        CartItem = apps.get_model("shop", "CartItem")
        Commande = apps.get_model("shop", "Commande")
        LigneCommande = apps.get_model("shop", "LigneCommande")
        Payment = apps.get_model("payments", "Payment")

        category = Categorie.objects.get(pk=self.category.pk)
        product = Produit.objects.get(pk=self.product.pk)
        self.assertEqual(category.nom_fr, "Catégorie historique")
        self.assertIsNone(category.nom_de)
        self.assertIsNone(category.nom_en)
        self.assertEqual(product.nom_fr, "Produit historique")
        self.assertEqual(product.description_fr, "Description historique exacte.")
        self.assertIsNone(product.nom_de)
        self.assertIsNone(product.nom_en)
        self.assertIsNone(product.description_de)
        self.assertIsNone(product.description_en)
        self.assertEqual(product.slug, "produit-historique-i18n")
        self.assertEqual(product.prix, Decimal("37.45"))
        self.assertEqual(product.image.name, "produits/historique.jpg")
        self.assertEqual(product.fichier.name, "produits/fichiers/historique.pdf")
        self.assertEqual(product.categorie_id, self.category.pk)
        self.assertTrue(product.en_vedette)

        self.assertEqual(User.objects.get(pk=self.user.pk).email, self.user.email)
        self.assertEqual(Cart.objects.count(), 1)
        self.assertEqual(CartItem.objects.get().quantite, 3)
        self.assertEqual(Commande.objects.get().source_cart_id, self.cart.pk)
        self.assertEqual(
            LigneCommande.objects.get().source_cart_item_id,
            self.cart_item.pk,
        )
        payment = Payment.objects.get(pk=self.payment.pk)
        self.assertEqual(payment.transaction_id, "catalog-migration-payment")
        self.assertEqual(payment.montant, Decimal("112.35"))
        self.assertEqual(payment.status, "SUCCESS")

    def test_migration_preserves_existing_french_values_and_is_idempotent(self):
        apps = self._migrate_and_get_apps()
        Categorie = apps.get_model("shop", "Categorie")
        Produit = apps.get_model("shop", "Produit")

        migration = import_module(
            "shop.migrations.0016_populate_french_product_category_translations"
        )
        with connection.schema_editor() as schema_editor:
            migration.populate_french_translations(apps, schema_editor)

        category = Categorie.objects.get(pk=self.preserved_category.pk)
        product = Produit.objects.get(pk=self.preserved_product.pk)
        self.assertEqual(category.nom_fr, "Catégorie française déjà renseignée")
        self.assertEqual(product.nom_fr, "Produit français déjà renseigné")
        self.assertEqual(
            product.description_fr,
            "Description française déjà renseignée.",
        )
        self.assertIsNone(category.nom_de)
        self.assertIsNone(category.nom_en)
        self.assertIsNone(product.nom_de)
        self.assertIsNone(product.nom_en)
