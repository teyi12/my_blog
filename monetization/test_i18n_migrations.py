from datetime import date
from decimal import Decimal
from importlib import import_module

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class MonetizationTranslationMigrationTests(TransactionTestCase):
    migrate_from = [("monetization", "0002_demandeaffiliation_demandepartenariat")]
    schema_target = [("monetization", "0003_abonnement_publicite_translations")]
    migrate_to = [("monetization", "0004_populate_french_monetization_translations")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        Partenaire = old_apps.get_model("monetization", "Partenaire")
        Abonnement = old_apps.get_model("monetization", "Abonnement")
        Publicite = old_apps.get_model("monetization", "Publicite")

        self.partner = Partenaire.objects.create(
            nom="Marque historique",
            site_web="https://example.test/partner",
            logo="sponsors/historique.png",
        )
        self.subscription = Abonnement.objects.create(
            nom="Abonnement historique exact",
            slug="abonnement-historique-exact",
            prix=Decimal("19.90"),
            duree_jours=90,
            description="Description historique exacte.",
        )
        self.preserved_subscription = Abonnement.objects.create(
            nom="Nom source à ne pas recopier",
            slug="traduction-francaise-preservee",
            prix=Decimal("5.00"),
            duree_jours=7,
            description="Description source à ne pas recopier.",
        )
        self.campaign = Publicite.objects.create(
            titre="Campagne historique exacte",
            partenaire=self.partner,
            image="publicites/historique.jpg",
            lien="https://example.test/campaign",
            date_debut=date(2026, 1, 1),
            date_fin=date(2026, 12, 31),
            actif=True,
        )
        self.preserved_campaign = Publicite.objects.create(
            titre="Titre source à ne pas recopier",
            partenaire=self.partner,
            image="publicites/preservee.jpg",
            lien="https://example.test/preserved",
            date_debut=date(2026, 2, 1),
            date_fin=date(2026, 2, 28),
            actif=False,
        )

        executor = MigrationExecutor(connection)
        executor.migrate(self.schema_target)
        schema_apps = executor.loader.project_state(self.schema_target).apps
        schema_apps.get_model("monetization", "Abonnement").objects.filter(
            pk=self.preserved_subscription.pk
        ).update(
            nom_fr="Abonnement français déjà renseigné",
            description_fr="Description française déjà renseignée.",
        )
        schema_apps.get_model("monetization", "Publicite").objects.filter(
            pk=self.preserved_campaign.pk
        ).update(titre_fr="Campagne française déjà renseignée")

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def _migrate_and_get_apps(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        return executor.loader.project_state(self.migrate_to).apps

    def test_migration_only_copies_historical_content_to_french_fields(self):
        apps = self._migrate_and_get_apps()
        Abonnement = apps.get_model("monetization", "Abonnement")
        Publicite = apps.get_model("monetization", "Publicite")

        subscription = Abonnement.objects.get(pk=self.subscription.pk)
        self.assertEqual(subscription.nom_fr, "Abonnement historique exact")
        self.assertEqual(subscription.description_fr, "Description historique exacte.")
        self.assertIsNone(subscription.nom_de)
        self.assertIsNone(subscription.nom_en)
        self.assertIsNone(subscription.description_de)
        self.assertIsNone(subscription.description_en)
        self.assertEqual(subscription.slug, "abonnement-historique-exact")
        self.assertEqual(subscription.prix, Decimal("19.90"))
        self.assertEqual(subscription.duree_jours, 90)

        campaign = Publicite.objects.get(pk=self.campaign.pk)
        self.assertEqual(campaign.titre_fr, "Campagne historique exacte")
        self.assertIsNone(campaign.titre_de)
        self.assertIsNone(campaign.titre_en)
        self.assertEqual(campaign.partenaire_id, self.partner.pk)
        self.assertEqual(campaign.image.name, "publicites/historique.jpg")
        self.assertEqual(campaign.lien, "https://example.test/campaign")
        self.assertTrue(campaign.actif)

    def test_existing_french_values_are_preserved_and_copy_is_idempotent(self):
        apps = self._migrate_and_get_apps()
        Abonnement = apps.get_model("monetization", "Abonnement")
        Publicite = apps.get_model("monetization", "Publicite")
        migration = import_module(
            "monetization.migrations.0004_populate_french_monetization_translations"
        )

        with connection.schema_editor() as schema_editor:
            migration.populate_french_monetization_translations(apps, schema_editor)

        subscription = Abonnement.objects.get(pk=self.preserved_subscription.pk)
        self.assertEqual(subscription.nom_fr, "Abonnement français déjà renseigné")
        self.assertEqual(
            subscription.description_fr,
            "Description française déjà renseignée.",
        )
        self.assertIsNone(subscription.nom_de)
        self.assertIsNone(subscription.nom_en)
        self.assertIsNone(subscription.description_de)
        self.assertIsNone(subscription.description_en)

        campaign = Publicite.objects.get(pk=self.preserved_campaign.pk)
        self.assertEqual(campaign.titre_fr, "Campagne française déjà renseignée")
        self.assertIsNone(campaign.titre_de)
        self.assertIsNone(campaign.titre_en)
        self.assertFalse(campaign.actif)
