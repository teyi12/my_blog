import re
from datetime import timedelta
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from payments.models import DonationPaymentAttempt, StripeSubscription

from .models import (
    Abonnement,
    AbonnementUtilisateur,
    DemandePartenariat,
    Partenaire,
    Publicite,
)
from .services import utilisateur_a_acces_premium


class HeadingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1_count = 0

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self.h1_count += 1


@override_settings(
    SUBSCRIPTIONS_ENABLED=True,
    DONATIONS_ENABLED=True,
    STRIPE_SECRET_KEY="sk_test_configured",
    STRIPE_WEBHOOK_SECRET="whsec_configured",
    IS_PRODUCTION=False,
)
class MonetizationPremiumUITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="monetization-ui@example.test",
            password="test-password",
        )
        cls.staff = get_user_model().objects.create_user(
            email="monetization-staff@example.test",
            password="test-password",
            is_staff=True,
        )
        cls.superuser = get_user_model().objects.create_superuser(
            email="monetization-superuser@example.test",
            password="test-password",
        )
        cls.plan = Abonnement.objects.create(
            nom="Premium Essentiel",
            slug="premium-essentiel-ui",
            prix=Decimal("8.50"),
            duree_jours=30,
            description="Accès aux contenus Premium publiés.",
            stripe_price_id="price_premium_ui",
        )
        cls.other_plan = Abonnement.objects.create(
            nom="Premium Longue durée",
            slug="premium-longue-duree-ui",
            prix=Decimal("21.00"),
            duree_jours=90,
            description="Accès aux contenus Premium publiés pendant 90 jours.",
            stripe_price_id="price_premium_long_ui",
        )

    def create_subscription(self, user=None, access=None, **overrides):
        values = {
            "utilisateur": user or self.user,
            "abonnement": self.plan,
            "montant": self.plan.prix,
            "devise": "EUR",
            "stripe_price_id": self.plan.stripe_price_id,
            "status": "ACTIVE",
            "stripe_checkout_session_id": "cs_must_not_render",
            "stripe_customer_id": "cus_must_not_render",
            "stripe_subscription_id": "sub_must_not_render",
            "abonnement_utilisateur": access,
            "current_period_start": timezone.now() - timedelta(days=2),
            "current_period_end": timezone.now() + timedelta(days=28),
            "raw_response": {"secret": "must-not-render"},
        }
        values.update(overrides)
        return StripeSubscription.objects.create(**values)

    def test_public_routes_use_the_real_templates_and_one_h1(self):
        routes = {
            "monetization:abonnements": "monetization/abonnements.html",
            "monetization:don": "monetization/don.html",
            "monetization:partenariat": "monetization/partenariat.html",
            "monetization:affiliation": "monetization/affiliation.html",
            "monetization:publicites": "monetization/publicites.html",
        }

        for route, template_name in routes.items():
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                parser = HeadingParser()
                parser.feed(response.content.decode())

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template_name)
                self.assertEqual(parser.h1_count, 1)
                self.assertContains(response, 'class="monetization-nav"')
                self.assertContains(response, 'aria-current="page"', count=1)

        self.assertRedirects(
            self.client.get(reverse("monetization:choice")),
            reverse("payments:choice"),
            fetch_redirect_response=False,
        )

    def test_staff_dashboard_and_legacy_revenue_alias_keep_their_permissions(self):
        for route in ("monetization:dashboard", "monetization:revenus"):
            with self.subTest(route=route):
                self.assertRedirects(
                    self.client.get(reverse(route)),
                    f'{reverse("home")}?next={reverse(route)}',
                )

        self.client.force_login(self.staff)
        for route in ("monetization:dashboard", "monetization:revenus"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "monetization/dashboard.html")

    def test_anonymous_expired_active_staff_and_superuser_states_are_preserved(self):
        subscribe_url = reverse(
            "monetization:souscrire_abonnement",
            args=[self.plan.slug],
        )
        anonymous = self.client.get(reverse("monetization:abonnements"))
        self.assertContains(anonymous, f'action="{subscribe_url}"')
        self.assertNotContains(anonymous, 'class="subscriber-panel"')

        expired = AbonnementUtilisateur.objects.create(
            utilisateur=self.user,
            abonnement=self.plan,
            date_fin=timezone.now() - timedelta(days=1),
            actif=True,
        )
        self.client.force_login(self.user)
        expired_page = self.client.get(reverse("monetization:abonnements"))
        self.assertFalse(utilisateur_a_acces_premium(self.user))
        self.assertContains(expired_page, f'action="{subscribe_url}"')

        expired.delete()
        active_access = AbonnementUtilisateur.objects.create(
            utilisateur=self.user,
            abonnement=self.plan,
            date_fin=timezone.now() + timedelta(days=30),
            actif=True,
        )
        self.create_subscription(access=active_access)
        active_page = self.client.get(reverse("monetization:abonnements"))
        self.assertContains(
            active_page,
            "subscription-card surface-card is-current",
            count=1,
        )
        self.assertContains(active_page, "subscription-current-status", count=1)
        self.assertNotContains(active_page, f'action="{subscribe_url}"')

        for privileged_user in (self.staff, self.superuser):
            with self.subTest(user=privileged_user.email):
                self.assertTrue(utilisateur_a_acces_premium(privileged_user))

    def test_provider_configuration_only_exposes_available_post_forms(self):
        subscribe_url = reverse(
            "monetization:souscrire_abonnement",
            args=[self.plan.slug],
        )
        enabled = self.client.get(reverse("monetization:abonnements"))
        self.assertContains(enabled, f'action="{subscribe_url}"')
        self.assertContains(enabled, 'method="post"')
        self.assertContains(enabled, 'name="csrfmiddlewaretoken"')

        with self.settings(SUBSCRIPTIONS_ENABLED=False):
            disabled = self.client.get(reverse("monetization:abonnements"))
        self.assertNotContains(disabled, f'action="{subscribe_url}"')
        self.assertContains(disabled, "momentanément indisponible")

        with self.settings(DONATIONS_ENABLED=False):
            donation_disabled = self.client.get(reverse("monetization:don"))
        self.assertNotContains(
            donation_disabled,
            f'action="{reverse("payments:create_donation_checkout")}"',
        )
        self.assertNotContains(donation_disabled, "Paiement traité par Stripe")

    def test_get_never_creates_financial_records(self):
        subscribe_url = reverse(
            "monetization:souscrire_abonnement",
            args=[self.plan.slug],
        )
        self.client.force_login(self.user)

        with patch("payments.subscriptions.stripe.checkout.Session.create") as subscribe:
            subscription_response = self.client.get(subscribe_url)
        with patch("payments.views.stripe.checkout.Session.create") as donate:
            donation_response = self.client.get(
                reverse("payments:create_donation_checkout")
            )

        self.assertEqual(subscription_response.status_code, 405)
        self.assertEqual(donation_response.status_code, 405)
        subscribe.assert_not_called()
        donate.assert_not_called()
        self.assertFalse(StripeSubscription.objects.exists())
        self.assertFalse(DonationPaymentAttempt.objects.exists())

    def test_invalid_donation_returns_bound_accessible_errors_without_side_effect(self):
        self.client.force_login(self.user)
        with patch("payments.views.stripe.checkout.Session.create") as create:
            response = self.client.post(
                reverse("payments:create_donation_checkout"),
                {"amount": "0.001"},
                follow=True,
            )

        self.assertRedirects(response, reverse("monetization:don"))
        self.assertContains(response, 'id="donation-error-summary-title"')
        self.assertContains(response, 'href="#donation-amount"')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(
            response,
            'aria-describedby="donation-amount-help donation-amount-errors"',
        )
        self.assertContains(response, 'value="0.001"')
        create.assert_not_called()
        self.assertFalse(DonationPaymentAttempt.objects.exists())

    def test_commercial_forms_keep_post_csrf_and_linked_errors(self):
        partnership_url = reverse("monetization:partenariat")
        response = self.client.post(partnership_url, {})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'method="post"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'id="partnership-error-summary-title"')
        self.assertContains(response, 'href="#id_nom"')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, 'aria-describedby="id_nom_errors"')

        valid = self.client.post(
            partnership_url,
            {
                "nom": "Ada",
                "email": "ada@example.test",
                "entreprise": "",
                "message": "Proposition éditoriale",
            },
        )
        self.assertRedirects(valid, partnership_url)
        self.assertEqual(DemandePartenariat.objects.count(), 1)

    def test_subscription_html_never_exposes_provider_or_raw_identifiers(self):
        access = AbonnementUtilisateur.objects.create(
            utilisateur=self.user,
            abonnement=self.plan,
            date_fin=timezone.now() + timedelta(days=30),
        )
        self.create_subscription(access=access)
        self.client.force_login(self.user)

        markup = self.client.get(reverse("monetization:abonnements")).content.decode()

        for secret in (
            self.plan.stripe_price_id,
            "cs_must_not_render",
            "cus_must_not_render",
            "sub_must_not_render",
            "must-not-render",
            settings.STRIPE_SECRET_KEY,
            settings.STRIPE_WEBHOOK_SECRET,
        ):
            self.assertNotIn(secret, markup)
        self.assertNotIn("|safe", markup)

    def test_campaign_page_filters_dates_and_avoids_partner_n_plus_one(self):
        now = timezone.now()
        for index in range(5):
            partner = Partenaire.objects.create(nom=f"Partenaire actif {index}")
            Publicite.objects.create(
                titre=f"Campagne active {index}",
                partenaire=partner,
                image=f"publicites/active-{index}.jpg",
                lien=f"https://example.test/active-{index}",
                ordre=index,
            )
        partner = Partenaire.objects.create(nom="Partenaire masqué")
        Publicite.objects.create(
            titre="Campagne future secrète",
            partenaire=partner,
            image="publicites/future.jpg",
            lien="https://example.test/future",
            date_debut=now + timedelta(days=1),
        )
        Publicite.objects.create(
            titre="Campagne expirée secrète",
            partenaire=partner,
            image="publicites/expired.jpg",
            lien="https://example.test/expired",
            date_fin=now - timedelta(days=1),
        )
        Publicite.objects.create(
            titre="Campagne inactive secrète",
            partenaire=partner,
            image="publicites/inactive.jpg",
            lien="https://example.test/inactive",
            actif=False,
        )

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("monetization:publicites"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'rel="sponsored noopener noreferrer"', count=10)
        self.assertContains(response, 'target="_blank"', count=10)
        self.assertNotContains(response, "secrète")
        campaign_queries = [
            query["sql"]
            for query in captured.captured_queries
            if "monetization_publicite" in query["sql"]
        ]
        self.assertEqual(len(campaign_queries), 1)
        self.assertIn("monetization_partenaire", campaign_queries[0])

    def test_empty_subscription_and_campaign_states_are_explicit(self):
        Abonnement.objects.all().delete()

        subscriptions = self.client.get(reverse("monetization:abonnements"))
        campaigns = self.client.get(reverse("monetization:publicites"))

        self.assertContains(
            subscriptions,
            'class="monetization-empty empty-state"',
            count=1,
        )
        self.assertNotContains(subscriptions, 'class="subscription-card')
        self.assertContains(
            campaigns,
            'class="monetization-empty empty-state"',
            count=1,
        )
        self.assertNotContains(campaigns, 'class="advertising-card')


class MonetizationPremiumUIStaticTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base_dir = Path(settings.BASE_DIR)
        cls.styles = (base_dir / "static/css/monetization.css").read_text(
            encoding="utf-8"
        )
        cls.subscription_styles = (
            base_dir / "static/css/subscriptions.css"
        ).read_text(encoding="utf-8")
        cls.templates = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (base_dir / "monetization/templates/monetization").glob(
                "*.html"
            )
        )

    def test_styles_use_defined_tokens_without_forbidden_overrides_or_raw_colors(self):
        combined = self.styles + self.subscription_styles
        global_styles = (
            Path(settings.BASE_DIR) / "static/css/styles.css"
        ).read_text(encoding="utf-8")
        used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", combined))
        defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", global_styles))

        self.assertEqual(used - defined, set())
        self.assertNotIn("!important", combined)
        self.assertNotIn("overflow-x:hidden", combined.replace(" ", ""))
        self.assertIsNone(re.search(r"#[0-9a-f]{3,8}\b", combined, re.I))
        self.assertIsNone(re.search(r"\brgba?\(", combined, re.I))
        self.assertNotIn(".subscription-card:hover", combined)
        self.assertNotIn(".advertising-card:hover", combined)

    def test_responsive_touch_and_accessibility_guards_are_present(self):
        self.assertIn("min-height: 2.75rem", self.styles)
        for breakpoint in ("63.99rem", "47.99rem", "24.99rem"):
            self.assertIn(f"max-width: {breakpoint}", self.styles)
        self.assertIn("overflow-wrap: anywhere", self.styles)
        self.assertIn("aria-current=\"page\"", self.templates)
        self.assertNotIn("|safe", self.templates)
