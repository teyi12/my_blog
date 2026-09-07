from datetime import date
from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import translation
from modeltranslation.admin import TranslationAdmin

from .admin import AbonnementAdmin, PubliciteAdmin
from .forms import AffiliationForm, PartenariatForm
from .models import Abonnement, Partenaire, Publicite, Revenu


class MonetizationI18nTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="member-monetization-i18n@example.com",
            password="test-password",
        )
        cls.staff = get_user_model().objects.create_user(
            email="staff-monetization-i18n@example.com",
            password="test-password",
            is_staff=True,
        )
        cls.plan = Abonnement.objects.create(
            nom="Formule Découverte",
            nom_fr="Formule Découverte",
            nom_de="Entdecker-Abo",
            nom_en="Discovery plan",
            slug="formule-decouverte",
            prix=Decimal("9.90"),
            duree_jours=30,
            description="Accès français aux contenus Premium.",
            description_fr="Accès français aux contenus Premium.",
            description_de="Deutscher Zugang zu Premium-Inhalten.",
            description_en="English access to Premium content.",
        )
        cls.fallback_plan = Abonnement.objects.create(
            nom="Formule française de secours",
            slug="formule-francaise-secours",
            prix=Decimal("4.90"),
            duree_jours=1,
            description="Description française de secours.",
        )
        cls.partner = Partenaire.objects.create(nom="Marque Exemple")
        cls.campaign = Publicite.objects.create(
            titre="Campagne française",
            titre_fr="Campagne française",
            titre_de="Deutsche Kampagne",
            titre_en="English campaign",
            partenaire=cls.partner,
            image="publicites/campagne.jpg",
            lien="https://example.test/campaign",
            date_debut=date(2026, 9, 1),
            date_fin=date(2026, 9, 30),
            actif=True,
        )

    def test_french_is_the_unprefixed_default_and_literal_fr_is_not_added(self):
        response = self.client.get("/monetization/abonnements/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<html lang="fr">')
        self.assertContains(response, "Choisissez la formule qui vous correspond.")
        self.assertContains(response, "Formule Découverte")
        self.assertEqual(self.client.get("/fr/monetization/abonnements/").status_code, 404)

    def test_german_subscription_page_translates_static_and_dynamic_content(self):
        response = self.client.get("/de/monetization/abonnements/")

        self.assertContains(response, '<html lang="de">')
        self.assertContains(response, "Wählen Sie das passende Angebot.")
        self.assertContains(response, "Entdecker-Abo")
        self.assertContains(response, "Deutscher Zugang zu Premium-Inhalten.")
        self.assertContains(response, "für 30 Tage")
        self.assertContains(response, "Dieses Angebot wählen")

    def test_english_subscription_page_translates_static_and_dynamic_content(self):
        response = self.client.get("/en/monetization/abonnements/")

        self.assertContains(response, '<html lang="en">')
        self.assertContains(response, "Choose the plan that suits you.")
        self.assertContains(response, "Discovery plan")
        self.assertContains(response, "English access to Premium content.")
        self.assertContains(response, "for 30 days")
        self.assertContains(response, "Choose this plan")

    def test_missing_german_and_english_dynamic_content_falls_back_to_french(self):
        for language in ("de", "en"):
            with self.subTest(language=language):
                response = self.client.get(f"/{language}/monetization/abonnements/")
                self.assertContains(response, "Formule française de secours")
                self.assertContains(response, "Description française de secours.")

    def test_slug_is_created_from_french_and_remains_stable(self):
        with translation.override("de"):
            plan = Abonnement.objects.create(
                nom_fr="Formule Française Stable",
                nom_de="Deutscher Name",
                nom_en="English name",
                prix=Decimal("12.00"),
                duree_jours=30,
                description_fr="Description française.",
            )

        self.assertEqual(plan.slug, "formule-francaise-stable")
        plan.nom_fr = "Nouveau nom français"
        plan.nom_de = "Neuer deutscher Name"
        plan.save()
        plan.refresh_from_db()
        self.assertEqual(plan.slug, "formule-francaise-stable")

    def test_same_subscription_slug_is_reversed_in_every_language(self):
        expected = {
            "fr": "/monetization/abonnements/formule-decouverte/souscrire/",
            "de": "/de/monetization/abonnements/formule-decouverte/souscrire/",
            "en": "/en/monetization/abonnements/formule-decouverte/souscrire/",
        }
        for language, path in expected.items():
            with self.subTest(language=language), translation.override(language):
                self.assertEqual(
                    reverse(
                        "monetization:souscrire_abonnement",
                        args=[self.plan.slug],
                    ),
                    path,
                )

    def test_public_campaign_uses_active_translation_and_keeps_partner_and_url(self):
        expected = {
            "fr": ("/monetization/publicites/", "Campagne française"),
            "de": ("/de/monetization/publicites/", "Deutsche Kampagne"),
            "en": ("/en/monetization/publicites/", "English campaign"),
        }
        for language, (path, title) in expected.items():
            with self.subTest(language=language):
                response = self.client.get(path)
                self.assertContains(response, title)
                self.assertContains(response, self.partner.nom)
                self.assertContains(response, self.campaign.lien)

    def test_donation_page_is_translated_without_changing_payment_endpoint(self):
        german = self.client.get("/de/monetization/don/")
        english = self.client.get("/en/monetization/don/")

        self.assertContains(german, "Wählen Sie Ihren Betrag")
        self.assertContains(german, "Melden Sie sich an, um sicher zu spenden.")
        self.assertContains(english, "Choose your amount")
        self.assertContains(english, "Sign in to make a secure donation.")

        self.client.force_login(self.user)
        authenticated = self.client.get("/en/monetization/don/")
        self.assertContains(authenticated, 'action="/payments/donate/"')
        self.assertEqual(reverse("payments:stripe_webhook"), "/payments/webhook/")
        self.assertEqual(reverse("payments:cinetpay_ipn"), "/payments/cinetpay/ipn/")

    def test_forms_and_validation_errors_use_the_active_language(self):
        german = self.client.post("/de/monetization/partenariat/", {})
        english = self.client.post("/en/monetization/affiliation/", {})

        self.assertContains(german, ">Name</label>")
        self.assertContains(german, "Dieses Feld ist erforderlich.")
        self.assertContains(english, ">Name</label>")
        self.assertContains(english, "This field is required.")

        with translation.override("de"):
            self.assertEqual(str(PartenariatForm().fields["entreprise"].label), "Unternehmen")
        with translation.override("en"):
            self.assertEqual(str(AffiliationForm().fields["produit"].label), "Product or service")

    def test_success_messages_are_translated_at_request_time(self):
        partnership = self.client.post(
            "/de/monetization/partenariat/",
            {
                "nom": "Ada",
                "email": "ada@example.test",
                "entreprise": "Example GmbH",
                "message": "Zusammenarbeit",
            },
            follow=True,
        )
        affiliation = self.client.post(
            "/en/monetization/affiliation/",
            {
                "nom": "Grace",
                "email": "grace@example.test",
                "plateforme": "Example",
                "produit": "Service",
                "message": "Proposal",
            },
            follow=True,
        )

        self.assertContains(
            partnership,
            "Ihre Kooperationsanfrage wurde erfolgreich gesendet.",
        )
        self.assertContains(
            affiliation,
            "Your affiliate request has been sent successfully.",
        )

    def test_subscription_information_message_uses_active_language(self):
        self.client.force_login(self.user)
        response = self.client.get(
            "/en/monetization/abonnements/formule-decouverte/souscrire/",
            follow=True,
        )

        self.assertContains(
            response,
            "Secure activation of the Discovery plan subscription will be available",
        )

    def test_staff_dashboard_translates_labels_and_revenue_type(self):
        Revenu.objects.create(type="DON", montant=Decimal("15.00"))
        self.client.force_login(self.staff)

        response = self.client.get("/de/monetization/dashboard/")

        self.assertContains(response, "Übersicht der erfassten Einnahmen.")
        self.assertContains(response, "Spenden")
        self.assertContains(response, "Spende")
        self.assertContains(response, "Zuletzt erfasste Einnahmen")


class MonetizationTranslationAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_superuser(
            email="admin-monetization-i18n@example.com",
            password="test-password",
        )

    def _request(self):
        request = RequestFactory().get("/admin/")
        request.user = self.staff
        return request

    def test_admin_exposes_translation_fields_and_stable_slug_configuration(self):
        subscription_admin = AbonnementAdmin(Abonnement, admin.site)
        advertising_admin = PubliciteAdmin(Publicite, admin.site)
        subscription_form = subscription_admin.get_form(self._request())
        advertising_form = advertising_admin.get_form(self._request())

        self.assertIsInstance(subscription_admin, TranslationAdmin)
        self.assertIsInstance(advertising_admin, TranslationAdmin)
        for field_name in (
            "nom_fr",
            "nom_de",
            "nom_en",
            "description_fr",
            "description_de",
            "description_en",
        ):
            self.assertIn(field_name, subscription_form.base_fields)
        for field_name in ("titre_fr", "titre_de", "titre_en"):
            self.assertIn(field_name, advertising_form.base_fields)
        self.assertEqual(subscription_admin.prepopulated_fields, {"slug": ("nom_fr",)})
