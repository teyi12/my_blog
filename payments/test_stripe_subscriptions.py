import json
import os
from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.backends.postgresql.base import DatabaseWrapper
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from blog.settings import env_bool
from monetization.models import Abonnement, AbonnementUtilisateur, Revenu

from .admin import (
    StripeSubscriptionAdmin,
    StripeSubscriptionInvoiceAdmin,
    StripeWebhookEventAdmin,
)
from .models import (
    StripeSubscription,
    StripeSubscriptionInvoice,
    StripeWebhookEvent,
)
from .subscriptions import subscriptions_are_available


class SubscriptionStructureTests(SimpleTestCase):
    def test_locking_queryset_compiles_for_postgresql_without_distinct(self):
        queryset = (
            StripeSubscription.objects.select_for_update()
            .filter(
                utilisateur_id=1,
                status__in=StripeSubscription.OPEN_STATUSES,
            )
            .order_by("pk")
        )
        postgresql_connection = DatabaseWrapper(
            {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "compile_only",
                "USER": "",
                "PASSWORD": "",
                "HOST": "",
                "PORT": "",
                "OPTIONS": {},
                "TIME_ZONE": None,
                "CONN_HEALTH_CHECKS": False,
                "CONN_MAX_AGE": 0,
                "AUTOCOMMIT": True,
            },
            alias="subscription_postgresql_compile_only",
        )
        with patch.object(
            postgresql_connection,
            "get_autocommit",
            return_value=False,
        ):
            sql, _ = queryset.query.get_compiler(
                connection=postgresql_connection
            ).as_sql()

        self.assertTrue(queryset.query.select_for_update)
        self.assertFalse(queryset.query.distinct)
        self.assertIn("FOR UPDATE", sql.upper())
        self.assertNotIn("DISTINCT", sql.upper())

    def test_provider_records_are_read_only_in_admin(self):
        admin_classes = (
            (StripeSubscription, StripeSubscriptionAdmin),
            (StripeSubscriptionInvoice, StripeSubscriptionInvoiceAdmin),
            (StripeWebhookEvent, StripeWebhookEventAdmin),
        )
        for model, admin_class in admin_classes:
            with self.subTest(model=model.__name__):
                model_admin = admin_class(model, admin.site)
                expected_fields = tuple(field.name for field in model._meta.fields)
                self.assertEqual(
                    model_admin.get_readonly_fields(None),
                    expected_fields,
                )
                self.assertFalse(model_admin.has_add_permission(None))
                self.assertFalse(model_admin.has_delete_permission(None))
                self.assertIsNone(model_admin.actions)


class SubscriptionAvailabilityTests(SimpleTestCase):
    plan = SimpleNamespace(
        stripe_price_id="price_server_plan",
        prix=Decimal("9.90"),
        duree_jours=30,
    )

    def test_environment_flag_is_false_when_absent_or_unknown(self):
        for environment in ({}, {"SUBSCRIPTIONS_ENABLED": "unknown"}):
            with self.subTest(environment=environment), patch.dict(
                os.environ,
                environment,
                clear=True,
            ):
                self.assertFalse(env_bool("SUBSCRIPTIONS_ENABLED", False))

    def test_environment_flag_accepts_only_explicit_true_values(self):
        for value in ("true", "TRUE", "1", "yes", "on"):
            with self.subTest(value=value), patch.dict(
                os.environ,
                {"SUBSCRIPTIONS_ENABLED": value},
                clear=True,
            ):
                self.assertTrue(env_bool("SUBSCRIPTIONS_ENABLED", False))

    @override_settings(
        SUBSCRIPTIONS_ENABLED=False,
        STRIPE_SECRET_KEY="sk_test_configured",
        STRIPE_WEBHOOK_SECRET="whsec_configured",
        IS_PRODUCTION=False,
    )
    def test_disabled_setting_blocks_subscriptions(self):
        self.assertFalse(subscriptions_are_available(self.plan))

    @override_settings(
        SUBSCRIPTIONS_ENABLED=True,
        STRIPE_SECRET_KEY="sk_test_configured",
        STRIPE_WEBHOOK_SECRET="whsec_configured",
        IS_PRODUCTION=True,
    )
    def test_test_key_is_rejected_in_production(self):
        self.assertFalse(subscriptions_are_available(self.plan))

    @override_settings(
        SUBSCRIPTIONS_ENABLED=True,
        STRIPE_SECRET_KEY="sk_live_configured",
        STRIPE_WEBHOOK_SECRET="whsec_configured",
        IS_PRODUCTION=True,
    )
    def test_live_key_can_enable_valid_plan_in_production(self):
        self.assertTrue(subscriptions_are_available(self.plan))

    @override_settings(
        SUBSCRIPTIONS_ENABLED=True,
        STRIPE_SECRET_KEY="sk_test_configured",
        STRIPE_WEBHOOK_SECRET="whsec_configured",
        IS_PRODUCTION=False,
    )
    def test_invalid_plan_configuration_blocks_subscriptions(self):
        invalid_plans = (
            SimpleNamespace(
                stripe_price_id=None,
                prix=Decimal("9.90"),
                duree_jours=30,
            ),
            SimpleNamespace(
                stripe_price_id="prod_invalid",
                prix=Decimal("9.90"),
                duree_jours=30,
            ),
            SimpleNamespace(
                stripe_price_id="price_valid",
                prix=Decimal("0"),
                duree_jours=30,
            ),
            SimpleNamespace(
                stripe_price_id="price_valid",
                prix=Decimal("9.90"),
                duree_jours=0,
            ),
        )
        for plan in invalid_plans:
            with self.subTest(plan=plan):
                self.assertFalse(subscriptions_are_available(plan))


@override_settings(
    SUBSCRIPTIONS_ENABLED=True,
    STRIPE_PRICE_MONTHLY="price_legacy_must_be_ignored",
    STRIPE_SECRET_KEY="sk_test_configured",
    STRIPE_WEBHOOK_SECRET="whsec_configured",
    IS_PRODUCTION=False,
)
class SubscriptionCheckoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="checkout-subscriber@example.com",
            password="test-password",
        )
        cls.plan = Abonnement.objects.create(
            nom="Premium Checkout",
            slug="premium-checkout",
            prix=Decimal("9.90"),
            duree_jours=30,
            description="Plan test",
            stripe_price_id="price_server_checkout",
        )

    def setUp(self):
        self.url = reverse(
            "monetization:souscrire_abonnement",
            args=[self.plan.slug],
        )
        self.client.force_login(self.user)

    @staticmethod
    def session():
        return SimpleNamespace(
            id="cs_subscription_checkout",
            url="https://checkout.stripe.test/subscription",
        )

    def test_get_is_rejected_without_creating_or_calling_stripe(self):
        with patch("payments.subscriptions.stripe.checkout.Session.create") as create:
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        create.assert_not_called()
        self.assertFalse(StripeSubscription.objects.exists())
        self.assertFalse(AbonnementUtilisateur.objects.exists())

    def test_anonymous_post_redirects_to_login_without_side_effect(self):
        self.client.logout()
        with patch("payments.subscriptions.stripe.checkout.Session.create") as create:
            response = self.client.post(self.url)

        self.assertRedirects(
            response,
            f'{reverse("accounts:login")}?next={self.url}',
        )
        create.assert_not_called()
        self.assertFalse(StripeSubscription.objects.exists())

    def test_valid_post_captures_server_values_and_metadata(self):
        with patch(
            "payments.subscriptions.stripe.checkout.Session.create",
            return_value=self.session(),
        ) as create:
            response = self.client.post(
                self.url,
                {
                    "price": "price_attacker",
                    "amount": "0.01",
                    "currency": "USD",
                    "status": "ACTIVE",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.session().url)
        subscription = StripeSubscription.objects.get()
        self.assertEqual(subscription.utilisateur, self.user)
        self.assertEqual(subscription.abonnement, self.plan)
        self.assertEqual(subscription.montant, self.plan.prix)
        self.assertEqual(subscription.devise, "EUR")
        self.assertEqual(subscription.stripe_price_id, self.plan.stripe_price_id)
        self.assertEqual(subscription.status, "PROCESSING")
        self.assertFalse(AbonnementUtilisateur.objects.exists())

        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["mode"], "subscription")
        self.assertEqual(
            kwargs["line_items"],
            [{"price": self.plan.stripe_price_id, "quantity": 1}],
        )
        self.assertEqual(kwargs["idempotency_key"], str(subscription.idempotency_key))
        expected_metadata = {
            "payment_kind": "subscription",
            "local_subscription_id": str(subscription.pk),
            "user_id": str(self.user.pk),
            "plan_id": str(self.plan.pk),
        }
        self.assertEqual(kwargs["metadata"], expected_metadata)
        self.assertEqual(kwargs["subscription_data"], {"metadata": expected_metadata})
        self.assertIn("payment_kind=subscription", kwargs["success_url"])

    def test_double_post_reuses_existing_checkout_url(self):
        with patch(
            "payments.subscriptions.stripe.checkout.Session.create",
            return_value=self.session(),
        ) as create:
            first = self.client.post(self.url)
            second = self.client.post(self.url)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(first.url, second.url)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(StripeSubscription.objects.count(), 1)

    def test_provider_failure_marks_attempt_failed_without_secret_details(self):
        with patch(
            "payments.subscriptions.stripe.checkout.Session.create",
            side_effect=RuntimeError("secret provider detail"),
        ):
            response = self.client.post(self.url)

        self.assertRedirects(response, reverse("monetization:abonnements"))
        subscription = StripeSubscription.objects.get()
        self.assertEqual(subscription.status, "FAILED")
        self.assertEqual(
            subscription.raw_response,
            {"stage": "initialization", "error_type": "RuntimeError"},
        )
        self.assertNotIn("secret", json.dumps(subscription.raw_response))
        self.assertFalse(AbonnementUtilisateur.objects.exists())

    def test_active_premium_access_blocks_new_checkout(self):
        AbonnementUtilisateur.objects.create(
            utilisateur=self.user,
            abonnement=self.plan,
            date_fin=timezone.now() + timedelta(days=30),
            actif=True,
        )
        with patch("payments.subscriptions.stripe.checkout.Session.create") as create:
            response = self.client.post(self.url)

        self.assertRedirects(response, reverse("monetization:abonnements"))
        create.assert_not_called()
        self.assertFalse(StripeSubscription.objects.exists())

    def test_plan_without_price_id_cannot_create_checkout(self):
        unavailable_plan = Abonnement.objects.create(
            nom="Sans Price",
            slug="sans-price",
            prix=Decimal("9.90"),
            duree_jours=30,
            description="Non configuré",
        )
        unavailable_url = reverse(
            "monetization:souscrire_abonnement",
            args=[unavailable_plan.slug],
        )

        with patch("payments.subscriptions.stripe.checkout.Session.create") as create:
            response = self.client.post(unavailable_url)

        self.assertRedirects(response, reverse("monetization:abonnements"))
        create.assert_not_called()
        self.assertFalse(StripeSubscription.objects.exists())
        page = self.client.get(reverse("monetization:abonnements"))
        self.assertNotContains(page, f'action="{unavailable_url}"')

    @override_settings(SUBSCRIPTIONS_ENABLED=False)
    def test_disabled_page_has_no_active_form(self):
        response = self.client.get(reverse("monetization:abonnements"))

        self.assertNotContains(response, f'action="{self.url}"')
        self.assertContains(response, "momentanément indisponible")

    @override_settings(SUBSCRIPTIONS_ENABLED=False)
    def test_disabled_page_and_success_notice_are_translated(self):
        cases = {
            "fr": (
                "/monetization/abonnements/",
                "Souscription sécurisée momentanément indisponible.",
                "Souscription en cours de confirmation",
            ),
            "de": (
                "/de/monetization/abonnements/",
                "Das sichere Abonnement ist vorübergehend nicht verfügbar.",
                "Abonnement wird bestätigt",
            ),
            "en": (
                "/en/monetization/abonnements/",
                "The secure subscription is temporarily unavailable.",
                "Subscription awaiting confirmation",
            ),
        }
        for language, (page_url, unavailable, success) in cases.items():
            with self.subTest(language=language):
                self.client.post(
                    reverse("set_language"),
                    {"language": language, "next": page_url},
                )
                page = self.client.get(page_url)
                success_page = self.client.get(
                    f'{reverse("payments:success")}?payment_kind=subscription'
                )
                self.assertContains(page, unavailable)
                self.assertContains(success_page, success)

    def test_enabled_page_has_csrf_post_form_without_client_values(self):
        response = self.client.get(reverse("monetization:abonnements"))

        self.assertContains(response, f'action="{self.url}"')
        self.assertContains(response, 'method="post"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertNotContains(response, 'name="price"')
        self.assertNotContains(response, 'name="amount"')
        self.assertNotContains(response, 'name="currency"')

    def test_price_id_validation_and_conditional_uniqueness(self):
        invalid = Abonnement(
            nom="Invalid",
            slug="invalid-price",
            prix=Decimal("1.00"),
            duree_jours=1,
            description="Invalid",
            stripe_price_id="product_invalid",
        )
        with self.assertRaises(ValidationError):
            invalid.full_clean()

        with self.assertRaises(IntegrityError), transaction.atomic():
            Abonnement.objects.create(
                nom="Duplicate",
                slug="duplicate-price",
                prix=Decimal("1.00"),
                duree_jours=1,
                description="Duplicate",
                stripe_price_id=self.plan.stripe_price_id,
            )

    def test_database_allows_only_one_open_subscription_per_user(self):
        StripeSubscription.objects.create(
            utilisateur=self.user,
            abonnement=self.plan,
            montant=self.plan.prix,
            devise="EUR",
            stripe_price_id=self.plan.stripe_price_id,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            StripeSubscription.objects.create(
                utilisateur=self.user,
                abonnement=self.plan,
                montant=self.plan.prix,
                devise="EUR",
                stripe_price_id=self.plan.stripe_price_id,
            )


@override_settings(
    STRIPE_WEBHOOK_SECRET="whsec_configured",
    SUBSCRIPTIONS_ENABLED=False,
)
class SubscriptionWebhookTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="webhook-subscriber@example.com",
            password="test-password",
        )
        cls.plan = Abonnement.objects.create(
            nom="Premium Webhook",
            slug="premium-webhook",
            prix=Decimal("9.90"),
            duree_jours=30,
            description="Plan webhook",
            stripe_price_id="price_server_webhook",
        )

    def setUp(self):
        self.webhook_url = reverse("payments:stripe_webhook")
        self.start = int(
            datetime(2026, 9, 1, tzinfo=datetime_timezone.utc).timestamp()
        )
        self.end = int(
            datetime(2026, 10, 1, tzinfo=datetime_timezone.utc).timestamp()
        )

    def local_subscription(self, **overrides):
        defaults = {
            "utilisateur": self.user,
            "abonnement": self.plan,
            "montant": Decimal("9.90"),
            "devise": "EUR",
            "stripe_price_id": self.plan.stripe_price_id,
            "status": "PROCESSING",
            "stripe_checkout_session_id": "cs_subscription_webhook",
            "checkout_url": "https://checkout.stripe.test/subscription",
        }
        defaults.update(overrides)
        return StripeSubscription.objects.create(**defaults)

    def metadata(self, subscription):
        return {
            "payment_kind": "subscription",
            "local_subscription_id": str(subscription.pk),
            "user_id": str(subscription.utilisateur_id),
            "plan_id": str(subscription.abonnement_id),
        }

    def checkout_event(self, subscription, event_id="evt_checkout", **overrides):
        session = {
            "id": subscription.stripe_checkout_session_id,
            "mode": "subscription",
            "payment_status": "paid",
            "amount_total": 990,
            "currency": "eur",
            "customer": "cus_subscription",
            "subscription": "sub_subscription",
            "metadata": self.metadata(subscription),
            "line_items": {
                "data": [{"price": {"id": subscription.stripe_price_id}}]
            },
        }
        session.update(overrides)
        return {
            "id": event_id,
            "type": "checkout.session.completed",
            "data": {"object": session},
        }

    def invoice_event(
        self,
        subscription,
        event_id="evt_invoice_paid",
        event_type="invoice.paid",
        invoice_id="in_subscription",
        **overrides,
    ):
        invoice = {
            "id": invoice_id,
            "subscription": "sub_subscription",
            "customer": "cus_subscription",
            "amount_paid": 990,
            "amount_due": 990,
            "currency": "eur",
            "status": "paid",
            "subscription_details": {"metadata": self.metadata(subscription)},
            "lines": {
                "data": [
                    {
                        "price": {"id": subscription.stripe_price_id},
                        "period": {"start": self.start, "end": self.end},
                    }
                ]
            },
        }
        invoice.update(overrides)
        return {
            "id": event_id,
            "type": event_type,
            "data": {"object": invoice},
        }

    def subscription_event(
        self,
        subscription,
        event_type,
        event_id,
        **overrides,
    ):
        payload = {
            "id": "sub_subscription",
            "customer": "cus_subscription",
            "status": "active",
            "cancel_at_period_end": False,
            "current_period_start": self.start,
            "current_period_end": self.end,
            "metadata": self.metadata(subscription),
            "items": {
                "data": [{"price": {"id": subscription.stripe_price_id}}]
            },
        }
        payload.update(overrides)
        return {
            "id": event_id,
            "type": event_type,
            "data": {"object": payload},
        }

    def post_event(self, event):
        with patch(
            "payments.views.stripe.Webhook.construct_event",
            return_value=event,
        ):
            return self.client.post(
                self.webhook_url,
                data=b"{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="signature",
            )

    def complete_checkout(self, subscription):
        response = self.post_event(self.checkout_event(subscription))
        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()

    def pay_invoice(self, subscription, **kwargs):
        response = self.post_event(self.invoice_event(subscription, **kwargs))
        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()

    def test_checkout_completed_only_correlates_without_premium_access(self):
        subscription = self.local_subscription()
        response = self.post_event(self.checkout_event(subscription))

        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, "CHECKOUT_COMPLETE")
        self.assertEqual(subscription.stripe_customer_id, "cus_subscription")
        self.assertEqual(subscription.stripe_subscription_id, "sub_subscription")
        self.assertFalse(AbonnementUtilisateur.objects.exists())
        self.assertFalse(Revenu.objects.exists())

    def test_invoice_paid_activates_once_and_records_invoice_and_revenue(self):
        subscription = self.local_subscription()
        self.complete_checkout(subscription)
        self.pay_invoice(subscription)

        self.assertEqual(subscription.status, "ACTIVE")
        self.assertEqual(AbonnementUtilisateur.objects.count(), 1)
        user_subscription = AbonnementUtilisateur.objects.get()
        self.assertEqual(subscription.abonnement_utilisateur, user_subscription)
        self.assertEqual(user_subscription.date_debut.timestamp(), self.start)
        self.assertEqual(user_subscription.date_fin.timestamp(), self.end)
        self.assertTrue(user_subscription.actif)
        self.assertEqual(StripeSubscriptionInvoice.objects.count(), 1)
        invoice = StripeSubscriptionInvoice.objects.get()
        self.assertEqual(invoice.montant_paye, Decimal("9.90"))
        self.assertEqual(invoice.revenu.type, "SUB")
        self.assertEqual(invoice.revenu.montant, Decimal("9.90"))
        self.assertEqual(Revenu.objects.count(), 1)

    def test_event_and_invoice_redelivery_are_both_idempotent(self):
        subscription = self.local_subscription()
        self.complete_checkout(subscription)
        event = self.invoice_event(subscription)

        first = self.post_event(event)
        same_event = self.post_event(event)
        other_event = self.post_event(
            self.invoice_event(subscription, event_id="evt_invoice_redelivery")
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(same_event.status_code, 200)
        self.assertEqual(other_event.status_code, 200)
        self.assertEqual(AbonnementUtilisateur.objects.count(), 1)
        self.assertEqual(StripeSubscriptionInvoice.objects.count(), 1)
        self.assertEqual(Revenu.objects.count(), 1)
        self.assertEqual(StripeWebhookEvent.objects.count(), 3)

    def test_invoice_paid_can_correlate_before_checkout_completed(self):
        subscription = self.local_subscription()
        response = self.post_event(self.invoice_event(subscription))

        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertEqual(subscription.stripe_subscription_id, "sub_subscription")
        self.assertEqual(subscription.status, "ACTIVE")
        self.assertEqual(AbonnementUtilisateur.objects.count(), 1)

    def test_subscription_update_before_checkout_correlates_without_activation(self):
        subscription = self.local_subscription()
        event = self.subscription_event(
            subscription,
            "customer.subscription.updated",
            "evt_early_subscription_updated",
        )

        response = self.post_event(event)

        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertEqual(subscription.stripe_subscription_id, "sub_subscription")
        self.assertEqual(subscription.status, "PROCESSING")
        self.assertFalse(AbonnementUtilisateur.objects.exists())
        self.assertFalse(Revenu.objects.exists())

    def test_unknown_local_subscription_is_retryable_and_not_marked(self):
        event = self.invoice_event(self.local_subscription())
        StripeSubscription.objects.all().delete()

        response = self.post_event(event)

        self.assertEqual(response.status_code, 409)
        self.assertFalse(StripeWebhookEvent.objects.exists())

    def test_payment_failed_does_not_extend_access_or_create_revenue(self):
        subscription = self.local_subscription()
        self.complete_checkout(subscription)
        self.pay_invoice(subscription)
        user_subscription = AbonnementUtilisateur.objects.get()
        paid_end = user_subscription.date_fin

        failed = self.invoice_event(
            subscription,
            event_id="evt_invoice_failed",
            event_type="invoice.payment_failed",
            invoice_id="in_failed",
            status="open",
            amount_paid=0,
        )
        response = self.post_event(failed)

        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        user_subscription.refresh_from_db()
        self.assertEqual(subscription.status, "PAST_DUE")
        self.assertEqual(user_subscription.date_fin, paid_end)
        self.assertTrue(user_subscription.actif)
        self.assertEqual(StripeSubscriptionInvoice.objects.count(), 1)
        self.assertEqual(Revenu.objects.count(), 1)

    def test_scheduled_cancellation_keeps_paid_access_unchanged(self):
        subscription = self.local_subscription()
        self.complete_checkout(subscription)
        self.pay_invoice(subscription)
        user_subscription = AbonnementUtilisateur.objects.get()
        paid_end = user_subscription.date_fin

        updated = self.subscription_event(
            subscription,
            "customer.subscription.updated",
            "evt_subscription_updated",
            cancel_at_period_end=True,
            current_period_end=self.end + 86400,
        )
        response = self.post_event(updated)

        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        user_subscription.refresh_from_db()
        self.assertEqual(subscription.status, "ACTIVE")
        self.assertTrue(subscription.cancel_at_period_end)
        self.assertEqual(user_subscription.date_fin, paid_end)
        self.assertTrue(user_subscription.actif)

    def test_subscription_deleted_disables_only_linked_access(self):
        subscription = self.local_subscription()
        self.complete_checkout(subscription)
        self.pay_invoice(subscription)
        linked = AbonnementUtilisateur.objects.get()
        historical = AbonnementUtilisateur.objects.create(
            utilisateur=self.user,
            abonnement=self.plan,
            date_fin=timezone.now() - timedelta(days=1),
            actif=True,
        )
        revenue_count_before_deletion = Revenu.objects.count()

        deleted = self.subscription_event(
            subscription,
            "customer.subscription.deleted",
            "evt_subscription_deleted",
            status="canceled",
        )
        response = self.post_event(deleted)

        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        linked.refresh_from_db()
        historical.refresh_from_db()
        self.assertEqual(subscription.status, "CANCELED")
        self.assertFalse(linked.actif)
        self.assertTrue(historical.actif)
        self.assertEqual(Revenu.objects.count(), revenue_count_before_deletion)

    def test_inconsistent_invoice_is_rejected_without_activation(self):
        mismatches = {
            "amount_paid": 989,
            "currency": "usd",
            "status": "open",
            "lines": {
                "data": [
                    {
                        "price": {"id": "price_wrong"},
                        "period": {"start": self.start, "end": self.end},
                    }
                ]
            },
            "subscription_details": {
                "metadata": {
                    "payment_kind": "subscription",
                    "local_subscription_id": "placeholder",
                    "user_id": "999999",
                    "plan_id": str(self.plan.pk),
                }
            },
        }
        for index, (field, value) in enumerate(mismatches.items()):
            with self.subTest(field=field):
                subscription = self.local_subscription(
                    stripe_checkout_session_id=f"cs_mismatch_{index}",
                )
                event = self.invoice_event(
                    subscription,
                    event_id=f"evt_mismatch_{index}",
                    invoice_id=f"in_mismatch_{index}",
                    **{field: value},
                )
                if field == "subscription_details":
                    event["data"]["object"][field]["metadata"][
                        "local_subscription_id"
                    ] = str(subscription.pk)

                response = self.post_event(event)

                self.assertEqual(response.status_code, 400)
                self.assertFalse(AbonnementUtilisateur.objects.exists())
                self.assertFalse(
                    StripeWebhookEvent.objects.filter(
                        stripe_event_id=f"evt_mismatch_{index}"
                    ).exists()
                )
                subscription.status = "FAILED"
                subscription.save(update_fields=["status"])

    def test_unrelated_subscription_event_is_ignored_cleanly(self):
        event = {
            "id": "evt_external_invoice",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_external",
                    "subscription": "sub_external",
                    "amount_paid": 100,
                    "currency": "eur",
                    "metadata": {},
                }
            },
        }

        response = self.post_event(event)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(StripeSubscriptionInvoice.objects.exists())
        self.assertFalse(AbonnementUtilisateur.objects.exists())
        self.assertFalse(Revenu.objects.exists())

    def test_unrelated_checkout_event_without_project_metadata_is_ignored(self):
        event = {
            "id": "evt_external_checkout",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_external",
                    "mode": "subscription",
                    "metadata": {},
                }
            },
        }

        response = self.post_event(event)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(StripeWebhookEvent.objects.exists())

    def tearDown(self):
        translation.activate("fr")
