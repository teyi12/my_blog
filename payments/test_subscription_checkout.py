from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from monetization.models import Abonnement, AbonnementUtilisateur


@override_settings(
    STRIPE_PRICE_MONTHLY="price_configured",
    STRIPE_SECRET_KEY="sk_test_configured",
    STRIPE_PUBLIC_KEY="pk_test_configured",
)
class DisabledSubscriptionCheckoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="subscriber@example.com",
            password="test-password",
        )
        cls.plan = Abonnement.objects.create(
            nom="Formule existante",
            slug="formule-existante",
            prix="9.90",
            duree_jours=30,
        )
        cls.user_subscription = AbonnementUtilisateur.objects.create(
            utilisateur=cls.user,
            abonnement=cls.plan,
            date_fin=timezone.now() + timedelta(days=30),
            actif=True,
        )

    def setUp(self):
        self.url = reverse("payments:create_subscription_checkout")
        self.subscriptions_url = reverse("monetization:abonnements")
        self.subscription_snapshot = list(
            AbonnementUtilisateur.objects.order_by("pk").values()
        )

    def _assert_subscription_unchanged(self):
        self.assertEqual(
            list(AbonnementUtilisateur.objects.order_by("pk").values()),
            self.subscription_snapshot,
        )

    def test_authenticated_get_is_neutralized(self):
        self.client.force_login(self.user)

        with patch("payments.views.stripe.checkout.Session.create") as create:
            response = self.client.get(self.url)

        self.assertRedirects(response, self.subscriptions_url)
        create.assert_not_called()
        self._assert_subscription_unchanged()

    def test_authenticated_post_is_neutralized(self):
        self.client.force_login(self.user)

        with patch("payments.views.stripe.checkout.Session.create") as create:
            response = self.client.post(self.url)

        self.assertRedirects(response, self.subscriptions_url)
        create.assert_not_called()
        self._assert_subscription_unchanged()

    def test_anonymous_user_is_redirected_to_login_without_stripe_call(self):
        with patch("payments.views.stripe.checkout.Session.create") as create:
            response = self.client.post(self.url)

        self.assertRedirects(
            response,
            f'{reverse("accounts:login")}?next={self.url}',
        )
        create.assert_not_called()
        self._assert_subscription_unchanged()

    def test_information_message_is_translated(self):
        self.client.force_login(self.user)
        expected_messages = {
            "fr": (
                "L’activation sécurisée de l’abonnement Premium sera disponible "
                "après intégration complète du paiement récurrent."
            ),
            "de": (
                "Die sichere Aktivierung des Abonnements Premium wird nach "
                "vollständiger Integration der wiederkehrenden Zahlung verfügbar sein."
            ),
            "en": (
                "Secure activation of the Premium subscription will be available "
                "once recurring payments have been fully integrated."
            ),
        }

        for language, expected in expected_messages.items():
            with self.subTest(language=language):
                self.client.post(
                    reverse("set_language"),
                    {"language": language, "next": self.url},
                )
                with patch(
                    "payments.views.stripe.checkout.Session.create"
                ) as create:
                    response = self.client.get(self.url, follow=True)

                self.assertContains(response, expected)
                create.assert_not_called()

    def test_public_subscription_page_keeps_safe_flow_only(self):
        response = self.client.get(self.subscriptions_url)

        self.assertContains(
            response,
            reverse(
                "monetization:souscrire_abonnement",
                args=[self.plan.slug],
            ),
        )
        self.assertNotContains(response, self.url)
        self.assertNotContains(response, "/payments/subscribe/")

    def test_existing_safe_subscription_flow_remains_neutralized(self):
        self.client.force_login(self.user)
        safe_url = reverse(
            "monetization:souscrire_abonnement",
            args=[self.plan.slug],
        )

        with patch("payments.views.stripe.checkout.Session.create") as create:
            response = self.client.get(safe_url)

        self.assertRedirects(response, self.subscriptions_url)
        create.assert_not_called()
        self._assert_subscription_unchanged()

    def tearDown(self):
        translation.activate("fr")
