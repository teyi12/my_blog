from datetime import timedelta

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone, translation
from modeltranslation.translator import translator

from .admin import PubliciteAdmin
from .models import Partenaire, Publicite


class AdvertisingCampaignModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.partner = Partenaire.objects.create(nom="Partenaire test")

    def campaign(self, **overrides):
        values = {
            "titre_fr": "Campagne active",
            "partenaire": self.partner,
            "image": "publicites/test.jpg",
            "lien": "https://example.test/campaign",
        }
        values.update(overrides)
        return Publicite(**values)

    def test_diffusables_only_returns_active_campaigns_inside_optional_period(self):
        moment = timezone.now()
        immediate = self.campaign(titre_fr="Immédiate", ordre=2)
        immediate.save()
        scheduled = self.campaign(
            titre_fr="Planifiée active",
            date_debut=moment - timedelta(hours=1),
            date_fin=moment + timedelta(hours=1),
            ordre=1,
        )
        scheduled.save()
        self.campaign(
            titre_fr="Future",
            date_debut=moment + timedelta(seconds=1),
        ).save()
        self.campaign(
            titre_fr="Expirée",
            date_fin=moment - timedelta(seconds=1),
        ).save()
        self.campaign(titre_fr="Inactive", actif=False).save()

        self.assertEqual(
            list(Publicite.objects.diffusables(moment)),
            [scheduled, immediate],
        )

    def test_diffusables_has_stable_order_by_order_then_primary_key(self):
        first = self.campaign(titre_fr="Première", ordre=3)
        first.save()
        second = self.campaign(titre_fr="Deuxième", ordre=3)
        second.save()
        leading = self.campaign(titre_fr="En tête", ordre=1)
        leading.save()

        self.assertEqual(
            list(Publicite.objects.diffusables().values_list("pk", flat=True)),
            [leading.pk, first.pk, second.pk],
        )

    def test_period_validation_rejects_an_end_before_the_start(self):
        campaign = self.campaign(
            date_debut=timezone.now(),
            date_fin=timezone.now() - timedelta(days=1),
        )

        with self.assertRaises(ValidationError) as context:
            campaign.full_clean()

        self.assertIn("date_fin", context.exception.message_dict)

    def test_destination_only_accepts_absolute_http_or_https_urls(self):
        invalid_urls = (
            "javascript:alert(1)",
            "data:text/html,test",
            "//example.test/campaign",
            "ftp://example.test/campaign",
            "mailto:ads@example.test",
        )
        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(ValidationError) as context:
                    self.campaign(lien=url).full_clean()
                self.assertIn("lien", context.exception.message_dict)

        for url in ("http://example.test/ad", "https://example.test/ad"):
            with self.subTest(url=url):
                self.campaign(lien=url).full_clean()

    def test_localized_alt_falls_back_to_french_then_title_then_partner(self):
        campaign = self.campaign(
            titre_de="Deutscher Titel",
            texte_alternatif_fr="Alternative française",
            texte_alternatif_de="",
        )
        with translation.override("de"):
            self.assertEqual(campaign.image_alt, "Alternative française")

        campaign.texte_alternatif_fr = ""
        with translation.override("de"):
            self.assertEqual(campaign.image_alt, "Deutscher Titel")

        campaign.titre_de = ""
        campaign.titre_fr = ""
        with translation.override("en"):
            self.assertEqual(campaign.image_alt, self.partner.nom)

    def test_all_public_campaign_copy_fields_are_registered_for_translation(self):
        options = translator.get_options_for_model(Publicite)
        self.assertEqual(
            set(options.fields),
            {"titre", "description", "texte_cta", "texte_alternatif"},
        )


class AdvertisingCarouselHomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.partner = Partenaire.objects.create(nom="Maison & Partenaire")

    def create_campaign(self, position=0, **overrides):
        values = {
            "titre_fr": f"Campagne {position}",
            "titre_de": f"Deutsche Kampagne {position}",
            "titre_en": f"English campaign {position}",
            "description_fr": "Description française.",
            "description_de": "Deutsche Beschreibung.",
            "description_en": "English description.",
            "texte_cta_fr": "Voir l’offre",
            "texte_cta_de": "Angebot ansehen",
            "texte_cta_en": "View offer",
            "texte_alternatif_fr": "Visuel français",
            "texte_alternatif_de": "Deutsches Motiv",
            "texte_alternatif_en": "English visual",
            "partenaire": self.partner,
            "image": f"publicites/campaign-{position}.jpg",
            "lien": f"https://example.test/campaign-{position}",
            "ordre": position,
        }
        values.update(overrides)
        return Publicite.objects.create(**values)

    def setUp(self):
        translation.activate("fr")
        self.addCleanup(translation.activate, "fr")

    def test_section_and_script_are_absent_without_a_public_campaign(self):
        response = self.client.get(reverse("home"))

        self.assertNotContains(response, 'data-home-section="advertising"')
        self.assertNotContains(response, "advertising-carousel.js")

    def test_one_campaign_is_disclosed_localized_and_has_no_rotation_controls(self):
        self.create_campaign()

        for language, expected in (
            ("fr", ("Campagne 0", "Description française.", "Visuel français", "Voir l’offre")),
            ("de", ("Deutsche Kampagne 0", "Deutsche Beschreibung.", "Deutsches Motiv", "Angebot ansehen")),
            ("en", ("English campaign 0", "English description.", "English visual", "View offer")),
            ("fr", ("Campagne 0", "Description française.", "Visuel français", "Voir l’offre")),
        ):
            path = "/" if language == "fr" else f"/{language}/"
            with self.subTest(language=language):
                response = self.client.get(path)
                for text in expected:
                    self.assertContains(response, text)
                self.assertContains(response, "Sponsorisé" if language == "fr" else ("Gesponsert" if language == "de" else "Sponsored"))
                self.assertContains(response, 'rel="sponsored noopener noreferrer"')
                self.assertContains(response, 'loading="lazy"')
                self.assertContains(response, 'width="1200"')
                self.assertContains(response, 'height="675"')
                self.assertNotContains(response, "data-advertising-controls")

    def test_multiple_campaigns_render_controls_indicators_and_fallback_list(self):
        for position in range(3):
            self.create_campaign(position)

        response = self.client.get(reverse("home"))

        self.assertContains(response, "data-advertising-slide", count=3)
        self.assertContains(response, "data-advertising-indicator", count=3)
        self.assertContains(response, "data-advertising-previous")
        self.assertContains(response, "data-advertising-next")
        self.assertContains(response, "data-advertising-pause")
        self.assertContains(response, "data-advertising-controls hidden")
        self.assertNotContains(response, "data-advertising-slide hidden")

    def test_home_limits_rendering_to_five_ordered_campaigns(self):
        campaigns = []
        for position in range(7):
            campaigns.append(self.create_campaign(position))

        response = self.client.get(reverse("home"))

        self.assertContains(response, "data-advertising-slide", count=5)
        self.assertEqual(
            [campaign.pk for campaign in response.context["publicites"]],
            [campaign.pk for campaign in campaigns[:5]],
        )

    def test_french_fallback_and_html_escaping_are_preserved(self):
        self.create_campaign(
            titre_fr='<script>alert("title")</script>',
            titre_de="",
            description_fr="<b>Description française</b>",
            description_de="",
            texte_cta_fr="Offre française",
            texte_cta_de="",
            texte_alternatif_fr='Image "française"',
            texte_alternatif_de="",
        )

        response = self.client.get("/de/")

        self.assertContains(response, '&lt;script&gt;alert(&quot;')
        self.assertContains(response, "&lt;b&gt;Description fran")
        self.assertNotContains(response, '<script>alert("title")</script>')
        self.assertNotContains(response, "<b>Description française</b>")
        self.assertContains(response, "Offre française")
        self.assertContains(response, 'alt="Image &quot;fran')

    def test_home_campaign_query_is_single_and_does_not_grow_with_partners(self):
        for position in range(5):
            partner = Partenaire.objects.create(nom=f"Partenaire {position}")
            self.create_campaign(position, partenaire=partner)

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        campaign_queries = [
            query["sql"]
            for query in captured.captured_queries
            if "monetization_publicite" in query["sql"]
        ]
        self.assertEqual(len(campaign_queries), 1)
        self.assertIn("monetization_partenaire", campaign_queries[0])

    def test_carousel_never_appears_on_cart_checkout_or_payment_pages(self):
        self.create_campaign()

        for path in (
            reverse("shop:panier"),
            reverse("shop:checkout"),
            reverse("payments:success"),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertNotContains(response, "data-advertising-carousel", status_code=response.status_code)
                self.assertNotContains(response, "advertising-carousel.js", status_code=response.status_code)


class AdvertisingCampaignAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.partner = Partenaire.objects.create(nom="Partenaire admin")

    def test_admin_exposes_campaign_fields_and_safe_statuses(self):
        model_admin = PubliciteAdmin(Publicite, admin.site)
        request = RequestFactory().get("/admin/")
        request.user = type("Staff", (), {"has_perm": lambda *args: True})()
        form = model_admin.get_form(request)

        for base_name in ("titre", "description", "texte_cta", "texte_alternatif"):
            for language in ("fr", "de", "en"):
                self.assertIn(f"{base_name}_{language}", form.base_fields)
        for field_name in (
            "partenaire",
            "image",
            "lien",
            "date_debut",
            "date_fin",
            "actif",
            "ordre",
        ):
            self.assertIn(field_name, form.base_fields)

        moment = timezone.now()
        base = {
            "titre_fr": "Campagne",
            "partenaire": self.partner,
            "image": "publicites/admin.jpg",
            "lien": "https://example.test/admin",
        }
        with translation.override("fr"):
            self.assertEqual(model_admin.diffusion_status(Publicite(**base)), "Active")
            self.assertEqual(
                model_admin.diffusion_status(
                    Publicite(**base, date_debut=moment + timedelta(days=1))
                ),
                "Future",
            )
            self.assertEqual(
                model_admin.diffusion_status(
                    Publicite(**base, date_fin=moment - timedelta(days=1))
                ),
                "Expirée",
            )
            self.assertEqual(
                model_admin.diffusion_status(Publicite(**base, actif=False)),
                "Inactive",
            )

    def test_admin_image_preview_escapes_advertiser_copy(self):
        model_admin = PubliciteAdmin(Publicite, admin.site)
        campaign = Publicite(
            titre_fr="Campagne",
            texte_alternatif_fr="<script>alert('preview')</script>",
            partenaire=self.partner,
            image="publicites/admin.jpg",
            lien="https://example.test/admin",
        )

        with translation.override("fr"):
            preview = str(model_admin.image_preview(campaign))

        self.assertNotIn("<script>", preview)
        self.assertIn("&lt;script&gt;", preview)
