from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class AdvertisingCampaignMigrationTests(TransactionTestCase):
    migrate_from = [("monetization", "0005_abonnement_stripe_price_id_and_more")]
    migrate_to = [
        (
            "monetization",
            "0006_alter_publicite_options_publicite_description_and_more",
        )
    ]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        Partner = old_apps.get_model("monetization", "Partenaire")
        Campaign = old_apps.get_model("monetization", "Publicite")
        partner = Partner.objects.create(nom="Annonceur historique")
        self.campaign_pk = Campaign.objects.create(
            titre="Campagne historique",
            titre_fr="Campagne historique",
            partenaire=partner,
            image="publicites/historique.jpg",
            lien="https://example.test/historique",
            date_debut=date(2026, 1, 1),
            date_fin=date(2026, 12, 31),
            actif=True,
        ).pk

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def migrate_forward(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        return executor.loader.project_state(self.migrate_to).apps

    def test_forward_migration_preserves_campaign_and_creates_no_advertisement(self):
        apps = self.migrate_forward()
        Campaign = apps.get_model("monetization", "Publicite")

        self.assertEqual(Campaign.objects.count(), 1)
        campaign = Campaign.objects.get(pk=self.campaign_pk)
        self.assertEqual(campaign.titre, "Campagne historique")
        self.assertEqual(campaign.lien, "https://example.test/historique")
        self.assertEqual(campaign.description, "")
        self.assertEqual(campaign.texte_cta, "")
        self.assertEqual(campaign.texte_alternatif, "")
        self.assertEqual(campaign.ordre, 0)
        self.assertIsNotNone(campaign.date_debut)
        self.assertIsNotNone(campaign.date_fin)
        self.assertEqual(
            (campaign.date_fin.hour, campaign.date_fin.minute, campaign.date_fin.second),
            (23, 59, 59),
        )

    def test_migration_is_reversible_without_losing_legacy_fields(self):
        self.migrate_forward()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        Campaign = old_apps.get_model("monetization", "Publicite")

        campaign = Campaign.objects.get(pk=self.campaign_pk)
        self.assertEqual(campaign.titre, "Campagne historique")
        self.assertEqual(campaign.image.name, "publicites/historique.jpg")
        self.assertEqual(campaign.lien, "https://example.test/historique")
        self.assertTrue(campaign.actif)
