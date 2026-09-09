from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from monetization.models import AbonnementUtilisateur

from .models import StripeSubscription


@override_settings(
    SUBSCRIPTIONS_ENABLED=True,
    STRIPE_PRICE_MONTHLY="price_legacy_configured",
    STRIPE_SECRET_KEY="sk_test_configured",
    STRIPE_WEBHOOK_SECRET="whsec_configured",
    IS_PRODUCTION=False,
)
class LegacyDisabledSubscriptionCheckoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="legacy-subscriber@example.com",
            password="test-password",
        )

    def setUp(self):
        self.url = reverse("payments:create_subscription_checkout")
        self.subscriptions_url = reverse("monetization:abonnements")

    def _assert_no_side_effect(self, create):
        create.assert_not_called()
        self.assertFalse(StripeSubscription.objects.exists())
        self.assertFalse(AbonnementUtilisateur.objects.exists())

    def test_authenticated_get_remains_neutralized(self):
        self.client.force_login(self.user)
        with patch("payments.views.stripe.checkout.Session.create") as create:
            response = self.client.get(self.url)

        self.assertRedirects(response, self.subscriptions_url)
        self._assert_no_side_effect(create)

    def test_authenticated_post_remains_neutralized(self):
        self.client.force_login(self.user)
        with patch("payments.views.stripe.checkout.Session.create") as create:
            response = self.client.post(self.url)

        self.assertRedirects(response, self.subscriptions_url)
        self._assert_no_side_effect(create)

    def test_anonymous_post_redirects_to_login_without_stripe(self):
        with patch("payments.views.stripe.checkout.Session.create") as create:
            response = self.client.post(self.url)

        self.assertRedirects(
            response,
            f'{reverse("accounts:login")}?next={self.url}',
        )
        self._assert_no_side_effect(create)
