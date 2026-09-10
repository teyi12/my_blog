from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import stripe
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from monetization.models import Abonnement, AbonnementUtilisateur

from .models import StripeSubscription
from .subscriptions import get_current_user_subscription


@override_settings(
    SUBSCRIPTIONS_ENABLED=True,
    STRIPE_SECRET_KEY="sk_test_configured",
    STRIPE_WEBHOOK_SECRET="whsec_configured",
    IS_PRODUCTION=False,
)
class SubscriptionSelfServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="subscriber-self-service@example.com",
            password="test-password",
        )
        cls.other_user = get_user_model().objects.create_user(
            email="other-subscriber@example.com",
            password="test-password",
        )
        cls.plan = Abonnement.objects.create(
            nom="Premium Sérénité",
            slug="premium-serenite",
            prix=Decimal("12.50"),
            duree_jours=30,
            description="Accès Premium de test.",
            stripe_price_id="price_self_service",
        )

    def setUp(self):
        self.profile_url = reverse("accounts:profile")
        self.subscriptions_url = reverse("monetization:abonnements")
        self.portal_url = reverse("payments:subscription_portal")
        self.subscribe_url = reverse(
            "monetization:souscrire_abonnement",
            args=[self.plan.slug],
        )

    def create_subscription(self, **overrides):
        defaults = {
            "utilisateur": self.user,
            "abonnement": self.plan,
            "montant": self.plan.prix,
            "devise": "EUR",
            "stripe_price_id": self.plan.stripe_price_id,
            "status": "ACTIVE",
            "stripe_checkout_session_id": "cs_self_service",
            "stripe_customer_id": "cus_self_service",
            "stripe_subscription_id": "sub_self_service",
            "current_period_start": timezone.now() - timedelta(days=5),
            "current_period_end": timezone.now() + timedelta(days=25),
            "raw_response": {"provider": "must-not-be-rendered"},
        }
        defaults.update(overrides)
        return StripeSubscription.objects.create(**defaults)

    def create_access(self, **overrides):
        defaults = {
            "utilisateur": self.user,
            "abonnement": self.plan,
            "date_fin": timezone.now() + timedelta(days=25),
            "actif": True,
        }
        defaults.update(overrides)
        return AbonnementUtilisateur.objects.create(**defaults)

    def test_selector_uses_priority_owner_filter_and_select_related(self):
        self.create_subscription(
            status="CANCELED",
            stripe_checkout_session_id="cs_terminal",
            stripe_subscription_id="sub_terminal",
        )
        access = self.create_access()
        active = self.create_subscription(
            abonnement_utilisateur=access,
            stripe_checkout_session_id="cs_active",
            stripe_subscription_id="sub_active",
        )
        self.create_subscription(
            utilisateur=self.other_user,
            status="PAST_DUE",
            stripe_checkout_session_id="cs_other",
            stripe_customer_id="cus_other",
            stripe_subscription_id="sub_other",
        )

        with self.assertNumQueries(1):
            current = get_current_user_subscription(self.user)

        self.assertEqual(current.pk, active.pk)
        with self.assertNumQueries(0):
            self.assertEqual(current.abonnement.pk, self.plan.pk)
            self.assertEqual(current.abonnement_utilisateur.pk, access.pk)

    def test_selector_returns_latest_terminal_subscription_and_none_for_anonymous(self):
        canceled = self.create_subscription(
            status="CANCELED",
            stripe_checkout_session_id="cs_canceled",
            stripe_subscription_id="sub_canceled",
        )
        failed = self.create_subscription(
            status="FAILED",
            stripe_checkout_session_id="cs_failed",
            stripe_subscription_id="sub_failed",
        )
        StripeSubscription.objects.filter(pk=canceled.pk).update(
            updated_at=timezone.now() - timedelta(days=2)
        )
        StripeSubscription.objects.filter(pk=failed.pk).update(
            updated_at=timezone.now() - timedelta(days=1)
        )

        self.assertEqual(get_current_user_subscription(self.user).pk, failed.pk)
        with self.assertNumQueries(0):
            self.assertIsNone(get_current_user_subscription(AnonymousUser()))

    def test_profile_and_subscription_page_render_active_details_without_stripe_ids(self):
        access = self.create_access()
        self.create_subscription(abonnement_utilisateur=access)
        self.client.force_login(self.user)

        for url in (self.profile_url, self.subscriptions_url):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Mon abonnement")
                self.assertContains(response, self.plan.nom)
                self.assertContains(response, "12,50 EUR")
                self.assertContains(response, "Accès Premium")
                self.assertContains(response, "Gérer mon abonnement")
                self.assertNotContains(response, "cus_self_service")
                self.assertNotContains(response, "sub_self_service")
                self.assertNotContains(response, "cs_self_service")
                self.assertNotContains(response, "must-not-be-rendered")

    def test_all_subscription_states_have_a_user_facing_summary(self):
        cases = (
            ("PROCESSING", False, "Initialisation en cours"),
            ("CHECKOUT_COMPLETE", False, "Confirmation en attente"),
            ("ACTIVE", False, "Votre abonnement est actif"),
            ("ACTIVE", True, "Votre accès reste actif jusqu’au"),
            ("PAST_DUE", False, "Paiement en retard"),
            ("CANCELED", False, "Cet abonnement est annulé"),
            ("FAILED", False, "Cette tentative de souscription a échoué"),
        )
        self.client.force_login(self.user)

        empty = self.client.get(self.profile_url)
        self.assertContains(empty, "aucun abonnement Stripe")

        for status, cancel_at_period_end, expected in cases:
            with self.subTest(status=status, cancel=cancel_at_period_end):
                subscription = self.create_subscription(
                    status=status,
                    cancel_at_period_end=cancel_at_period_end,
                )
                profile = self.client.get(self.profile_url)
                self.assertContains(profile, expected)
                subscription.delete()

    def test_past_due_invites_user_to_manage_payment_method(self):
        self.create_subscription(status="PAST_DUE")
        self.client.force_login(self.user)

        response = self.client.get(self.subscriptions_url)

        self.assertContains(response, "Gérer mon moyen de paiement")
        self.assertNotContains(response, f'action="{self.subscribe_url}"')

    def test_open_subscription_hides_new_checkout_but_terminal_allows_it(self):
        self.client.force_login(self.user)
        active = self.create_subscription()

        active_page = self.client.get(self.subscriptions_url)

        self.assertNotContains(active_page, f'action="{self.subscribe_url}"')
        self.assertContains(active_page, "Une souscription est déjà en cours")

        active.delete()
        self.create_subscription(status="CANCELED")
        terminal_page = self.client.get(self.subscriptions_url)
        self.assertContains(terminal_page, f'action="{self.subscribe_url}"')

        with self.settings(SUBSCRIPTIONS_ENABLED=False):
            disabled_page = self.client.get(self.subscriptions_url)
        self.assertNotContains(disabled_page, f'action="{self.subscribe_url}"')

    def test_anonymous_page_keeps_public_offers_without_private_summary(self):
        response = self.client.get(self.subscriptions_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'action="{self.subscribe_url}"')
        self.assertNotContains(response, "Mon abonnement")

    @override_settings(SUBSCRIPTIONS_ENABLED=False)
    def test_portal_uses_server_owned_customer_and_return_url_when_checkout_disabled(self):
        access = self.create_access()
        subscription = self.create_subscription(abonnement_utilisateur=access)
        self.client.force_login(self.user)
        portal_session = SimpleNamespace(
            url="https://billing.stripe.test/session/self-service"
        )

        with patch(
            "payments.subscriptions.stripe.billing_portal.Session.create",
            return_value=portal_session,
        ) as create:
            response = self.client.post(
                self.portal_url,
                {
                    "customer": "cus_attacker",
                    "subscription": "sub_attacker",
                    "return_url": "https://attacker.example/",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, portal_session.url)
        create.assert_called_once_with(
            customer=subscription.stripe_customer_id,
            return_url=f"http://testserver{self.subscriptions_url}",
        )
        subscription.refresh_from_db()
        access.refresh_from_db()
        self.assertEqual(subscription.status, "ACTIVE")
        self.assertTrue(access.actif)

    def test_portal_requires_authentication_post_and_csrf(self):
        self.create_subscription()

        anonymous = self.client.post(self.portal_url)
        self.assertRedirects(
            anonymous,
            f'{reverse("accounts:login")}?next={self.portal_url}',
        )

        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.portal_url).status_code, 405)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        with patch(
            "payments.subscriptions.stripe.billing_portal.Session.create"
        ) as create:
            forbidden = csrf_client.post(self.portal_url)
        self.assertEqual(forbidden.status_code, 403)
        create.assert_not_called()

    def test_portal_never_uses_another_users_subscription(self):
        self.create_subscription(
            utilisateur=self.other_user,
            stripe_checkout_session_id="cs_other",
            stripe_customer_id="cus_other",
            stripe_subscription_id="sub_other",
        )
        self.client.force_login(self.user)

        with patch(
            "payments.subscriptions.stripe.billing_portal.Session.create"
        ) as create:
            response = self.client.post(
                self.portal_url,
                {"customer": "cus_other", "subscription": "sub_other"},
            )

        self.assertRedirects(response, self.subscriptions_url)
        create.assert_not_called()

    def test_portal_provider_error_is_controlled_and_logs_no_provider_details(self):
        self.create_subscription()
        self.client.force_login(self.user)
        provider_detail = "provider response with private customer data"

        with self.assertLogs("payments.subscriptions", level="WARNING") as logs:
            with patch(
                "payments.subscriptions.stripe.billing_portal.Session.create",
                side_effect=stripe.StripeError(provider_detail),
            ):
                response = self.client.post(self.portal_url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "temporairement indisponible")
        log_output = "\n".join(logs.output)
        self.assertIn("StripeError", log_output)
        self.assertNotIn(provider_detail, log_output)
        self.assertNotIn("cus_self_service", log_output)

    def test_portal_without_customer_is_unavailable_without_provider_call(self):
        self.create_subscription(stripe_customer_id=None)
        self.client.force_login(self.user)

        with patch(
            "payments.subscriptions.stripe.billing_portal.Session.create"
        ) as create:
            response = self.client.post(self.portal_url)

        self.assertRedirects(response, self.subscriptions_url)
        create.assert_not_called()

    def test_self_service_labels_are_translated(self):
        self.create_subscription()
        self.client.force_login(self.user)

        english = self.client.get("/en/monetization/abonnements/")
        german = self.client.get("/de/monetization/abonnements/")

        self.assertContains(english, "My subscription")
        self.assertContains(english, "Manage my subscription")
        self.assertContains(german, "Mein Abonnement")
        self.assertContains(german, "Abonnement verwalten")
