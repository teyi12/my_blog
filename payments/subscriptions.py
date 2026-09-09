import logging
import re
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal, InvalidOperation

import stripe
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from monetization.models import AbonnementUtilisateur, Revenu
from monetization.services import utilisateur_a_acces_premium

from .models import (
    StripeSubscription,
    StripeSubscriptionInvoice,
    StripeWebhookEvent,
)


logger = logging.getLogger(__name__)
LIVE_SECRET_KEY_PREFIXES = ("sk_live_", "rk_live_")
PRICE_ID_PATTERN = re.compile(r"^price_[A-Za-z0-9_]+$")
SUBSCRIPTION_EVENT_TYPES = {
    "checkout.session.completed",
    "invoice.paid",
    "invoice.payment_failed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}


class SubscriptionUnavailable(Exception):
    pass


class SubscriptionAlreadyActive(Exception):
    pass


class SubscriptionConflict(Exception):
    pass


class SubscriptionInitializationInProgress(Exception):
    pass


class SubscriptionProviderError(Exception):
    pass


class SubscriptionWebhookMismatch(Exception):
    pass


class SubscriptionWebhookRetry(Exception):
    pass


def subscriptions_are_available(plan=None):
    """Return whether recurring billing is safely enabled globally/for a plan."""
    if getattr(settings, "SUBSCRIPTIONS_ENABLED", False) is not True:
        return False

    secret_key = str(getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()
    webhook_secret = str(
        getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or ""
    ).strip()
    if not secret_key or not webhook_secret:
        return False
    if getattr(settings, "IS_PRODUCTION", False) and not secret_key.startswith(
        LIVE_SECRET_KEY_PREFIXES
    ):
        return False

    if plan is None:
        return True

    price_id = str(getattr(plan, "stripe_price_id", "") or "").strip()
    if not PRICE_ID_PATTERN.fullmatch(price_id):
        return False
    try:
        if Decimal(str(plan.prix)) <= 0 or int(plan.duree_jours) <= 0:
            return False
    except (InvalidOperation, TypeError, ValueError):
        return False
    return True


def _value(obj, key):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except (KeyError, TypeError):
            pass
    return getattr(obj, key, None)


def _path(obj, *parts):
    current = obj
    for part in parts:
        if isinstance(part, int):
            try:
                current = current[part]
            except (IndexError, KeyError, TypeError):
                return None
        else:
            current = _value(current, part)
        if current is None:
            return None
    return current


def _provider_id(value):
    if value is None:
        return None
    nested_id = _value(value, "id")
    if nested_id:
        return str(nested_id)
    if isinstance(value, str):
        return value
    return None


def _local_pk(value):
    if isinstance(value, bool):
        raise SubscriptionWebhookMismatch
    try:
        local_id = int(value)
    except (TypeError, ValueError):
        raise SubscriptionWebhookMismatch from None
    if local_id <= 0:
        raise SubscriptionWebhookMismatch
    return local_id


def _minor_amount(amount):
    value = Decimal(str(amount)) * 100
    if value != value.to_integral_value():
        raise SubscriptionWebhookMismatch
    return int(value)


def _datetime_from_stripe(value):
    if isinstance(value, bool):
        raise SubscriptionWebhookMismatch
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        raise SubscriptionWebhookMismatch from None
    if timestamp <= 0:
        raise SubscriptionWebhookMismatch
    return datetime.fromtimestamp(timestamp, tz=datetime_timezone.utc)


def _metadata(obj):
    candidates = (
        _path(obj, "metadata"),
        _path(obj, "subscription_details", "metadata"),
        _path(obj, "parent", "subscription_details", "metadata"),
        _path(obj, "lines", "data", 0, "metadata"),
    )
    for candidate in candidates:
        if candidate:
            return candidate
    return {}


def _subscription_id_from_invoice(invoice):
    for candidate in (
        _path(invoice, "subscription"),
        _path(invoice, "subscription_details", "subscription"),
        _path(invoice, "parent", "subscription_details", "subscription"),
    ):
        provider_id = _provider_id(candidate)
        if provider_id:
            return provider_id
    return None


def _price_id(obj):
    candidates = (
        _path(obj, "lines", "data", 0, "price"),
        _path(obj, "lines", "data", 0, "pricing", "price_details", "price"),
        _path(obj, "items", "data", 0, "price"),
        _path(obj, "line_items", "data", 0, "price"),
    )
    for candidate in candidates:
        provider_id = _provider_id(candidate)
        if provider_id:
            return provider_id
    return None


def _invoice_period(invoice):
    start = _path(invoice, "lines", "data", 0, "period", "start")
    end = _path(invoice, "lines", "data", 0, "period", "end")
    if start is None or end is None:
        start = _path(invoice, "period_start")
        end = _path(invoice, "period_end")
    period_start = _datetime_from_stripe(start)
    period_end = _datetime_from_stripe(end)
    if period_end <= period_start:
        raise SubscriptionWebhookMismatch
    return period_start, period_end


def _subscription_period(subscription):
    start = _path(subscription, "current_period_start")
    end = _path(subscription, "current_period_end")
    if start is None or end is None:
        start = _path(subscription, "items", "data", 0, "current_period_start")
        end = _path(subscription, "items", "data", 0, "current_period_end")
    if start is None and end is None:
        return None, None
    period_start = _datetime_from_stripe(start)
    period_end = _datetime_from_stripe(end)
    if period_end <= period_start:
        raise SubscriptionWebhookMismatch
    return period_start, period_end


def _validate_metadata(local_subscription, metadata, required=False):
    payment_kind = str(_value(metadata, "payment_kind") or "")
    local_id = str(_value(metadata, "local_subscription_id") or "")
    user_id = str(_value(metadata, "user_id") or "")
    plan_id = str(_value(metadata, "plan_id") or "")
    has_project_metadata = any((payment_kind, local_id, user_id, plan_id))
    if required or has_project_metadata:
        if (
            payment_kind != "subscription"
            or local_id != str(local_subscription.pk)
            or user_id != str(local_subscription.utilisateur_id)
            or plan_id != str(local_subscription.abonnement_id)
        ):
            raise SubscriptionWebhookMismatch


def _find_local_subscription(provider_subscription_id, metadata):
    queryset = StripeSubscription.objects.select_for_update()
    local_subscription = None
    if provider_subscription_id:
        local_subscription = queryset.filter(
            stripe_subscription_id=provider_subscription_id
        ).first()

    metadata_kind = str(_value(metadata, "payment_kind") or "")
    metadata_local_id = _value(metadata, "local_subscription_id")
    if local_subscription is None and metadata_kind == "subscription":
        if not metadata_local_id:
            raise SubscriptionWebhookMismatch
        local_subscription = queryset.filter(pk=_local_pk(metadata_local_id)).first()
        if local_subscription is None:
            raise SubscriptionWebhookRetry

    if local_subscription is None:
        return None

    _validate_metadata(local_subscription, metadata)
    if (
        provider_subscription_id
        and local_subscription.stripe_subscription_id
        and local_subscription.stripe_subscription_id != provider_subscription_id
    ):
        raise SubscriptionWebhookMismatch
    return local_subscription


def _subscription_metadata(local_subscription):
    return {
        "payment_kind": "subscription",
        "local_subscription_id": str(local_subscription.pk),
        "user_id": str(local_subscription.utilisateur_id),
        "plan_id": str(local_subscription.abonnement_id),
    }


def initialize_subscription_checkout(request, plan):
    """Reserve locally before creating or reusing a Stripe Checkout Session."""
    if not subscriptions_are_available(plan):
        raise SubscriptionUnavailable
    if utilisateur_a_acces_premium(request.user):
        raise SubscriptionAlreadyActive

    try:
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(
                pk=request.user.pk
            )
            existing = (
                StripeSubscription.objects.select_for_update()
                .filter(
                    utilisateur=user,
                    status__in=StripeSubscription.OPEN_STATUSES,
                )
                .order_by("pk")
                .first()
            )
            if existing:
                if (
                    existing.abonnement_id == plan.pk
                    and existing.status == "PROCESSING"
                    and existing.checkout_url
                ):
                    return existing
                if existing.status == "PROCESSING" and not existing.checkout_url:
                    raise SubscriptionInitializationInProgress
                raise SubscriptionConflict

            local_subscription = StripeSubscription.objects.create(
                utilisateur=user,
                abonnement=plan,
                montant=plan.prix,
                devise="EUR",
                stripe_price_id=plan.stripe_price_id,
                status="PROCESSING",
            )
    except IntegrityError:
        raise SubscriptionConflict from None

    metadata = _subscription_metadata(local_subscription)
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[
                {"price": local_subscription.stripe_price_id, "quantity": 1}
            ],
            success_url=request.build_absolute_uri(
                f'{reverse("payments:success")}?payment_kind=subscription'
            ),
            cancel_url=request.build_absolute_uri(reverse("payments:cancel")),
            customer_email=request.user.email or None,
            metadata=metadata,
            subscription_data={"metadata": metadata},
            idempotency_key=str(local_subscription.idempotency_key),
        )
        session_id = _provider_id(session)
        checkout_url = str(_value(session, "url") or "")
        if not session_id or not checkout_url:
            raise ValueError("incomplete provider response")

        with transaction.atomic():
            locked = StripeSubscription.objects.select_for_update().get(
                pk=local_subscription.pk
            )
            if locked.status != "PROCESSING":
                raise SubscriptionConflict
            locked.stripe_checkout_session_id = session_id
            locked.checkout_url = checkout_url
            locked.raw_response = {
                "stage": "checkout_created",
                "checkout_session_id": session_id,
            }
            locked.save(
                update_fields=[
                    "stripe_checkout_session_id",
                    "checkout_url",
                    "raw_response",
                    "updated_at",
                ]
            )
            return locked
    except (SubscriptionConflict, SubscriptionInitializationInProgress):
        raise
    except Exception as exc:
        with transaction.atomic():
            locked = StripeSubscription.objects.select_for_update().get(
                pk=local_subscription.pk
            )
            if locked.status == "PROCESSING":
                locked.status = "FAILED"
                locked.raw_response = {
                    "stage": "initialization",
                    "error_type": type(exc).__name__,
                }
                locked.save(
                    update_fields=["status", "raw_response", "updated_at"]
                )
        logger.warning(
            "Stripe subscription checkout initialization failed (%s)",
            type(exc).__name__,
        )
        raise SubscriptionProviderError from None


def _handle_checkout_completed(session):
    metadata = _metadata(session)
    if str(_value(metadata, "payment_kind") or "") != "subscription":
        return False
    local_id = _value(metadata, "local_subscription_id")
    if not local_id:
        raise SubscriptionWebhookMismatch
    local_subscription = StripeSubscription.objects.select_for_update().filter(
        pk=_local_pk(local_id)
    ).first()
    if local_subscription is None:
        raise SubscriptionWebhookRetry
    _validate_metadata(local_subscription, metadata, required=True)

    session_id = _provider_id(session)
    provider_subscription_id = _provider_id(_value(session, "subscription"))
    customer_id = _provider_id(_value(session, "customer"))
    currency = str(_value(session, "currency") or "").upper()
    amount_total = _value(session, "amount_total")
    mode = _value(session, "mode")
    payload_price_id = _price_id(session)
    if (
        not session_id
        or session_id != local_subscription.stripe_checkout_session_id
        or not provider_subscription_id
        or not customer_id
        or currency != local_subscription.devise
        or amount_total != _minor_amount(local_subscription.montant)
        or (mode is not None and mode != "subscription")
        or (
            payload_price_id is not None
            and payload_price_id != local_subscription.stripe_price_id
        )
        or (
            local_subscription.stripe_subscription_id
            and local_subscription.stripe_subscription_id
            != provider_subscription_id
        )
    ):
        raise SubscriptionWebhookMismatch

    local_subscription.stripe_customer_id = customer_id
    local_subscription.stripe_subscription_id = provider_subscription_id
    if local_subscription.status == "PROCESSING":
        local_subscription.status = "CHECKOUT_COMPLETE"
    local_subscription.raw_response = {
        "stage": "checkout_completed",
        "checkout_session_id": session_id,
        "customer_id": customer_id,
        "subscription_id": provider_subscription_id,
        "payment_status": _value(session, "payment_status"),
    }
    local_subscription.save(
        update_fields=[
            "stripe_customer_id",
            "stripe_subscription_id",
            "status",
            "raw_response",
            "updated_at",
        ]
    )
    return True


def _validate_invoice(local_subscription, invoice, amount_field):
    invoice_id = _provider_id(invoice)
    currency = str(_value(invoice, "currency") or "").upper()
    amount = _value(invoice, amount_field)
    price_id = _price_id(invoice)
    if (
        not invoice_id
        or currency != local_subscription.devise
        or amount != _minor_amount(local_subscription.montant)
        or price_id != local_subscription.stripe_price_id
    ):
        raise SubscriptionWebhookMismatch
    return invoice_id


def _handle_invoice_paid(invoice):
    metadata = _metadata(invoice)
    provider_subscription_id = _subscription_id_from_invoice(invoice)
    local_subscription = _find_local_subscription(
        provider_subscription_id,
        metadata,
    )
    if local_subscription is None:
        return False
    if not provider_subscription_id:
        raise SubscriptionWebhookMismatch

    if str(_value(invoice, "status") or "") != "paid" or _value(
        invoice, "paid"
    ) is False:
        raise SubscriptionWebhookMismatch
    invoice_id = _validate_invoice(local_subscription, invoice, "amount_paid")
    period_start, period_end = _invoice_period(invoice)
    if provider_subscription_id and not local_subscription.stripe_subscription_id:
        local_subscription.stripe_subscription_id = provider_subscription_id

    customer_id = _provider_id(_value(invoice, "customer"))
    if customer_id:
        if (
            local_subscription.stripe_customer_id
            and local_subscription.stripe_customer_id != customer_id
        ):
            raise SubscriptionWebhookMismatch
        local_subscription.stripe_customer_id = customer_id

    if local_subscription.abonnement_utilisateur_id:
        user_subscription = AbonnementUtilisateur.objects.select_for_update().get(
            pk=local_subscription.abonnement_utilisateur_id
        )
        if (
            user_subscription.utilisateur_id != local_subscription.utilisateur_id
            or user_subscription.abonnement_id != local_subscription.abonnement_id
        ):
            raise SubscriptionWebhookMismatch
        user_subscription.date_debut = period_start
        user_subscription.date_fin = period_end
        user_subscription.actif = True
        user_subscription.save(
            update_fields=["date_debut", "date_fin", "actif"]
        )
    else:
        user_subscription = AbonnementUtilisateur(
            utilisateur=local_subscription.utilisateur,
            abonnement=local_subscription.abonnement,
            date_fin=period_end,
            actif=True,
        )
        # Le signal historique crée un revenu générique à chaque create().
        # Le flux Stripe contourne ce signal pour rattacher exactement un revenu
        # à la facture signée qui justifie l'activation.
        AbonnementUtilisateur.objects.bulk_create([user_subscription])
        AbonnementUtilisateur.objects.filter(pk=user_subscription.pk).update(
            date_debut=period_start
        )
        user_subscription.date_debut = period_start
        local_subscription.abonnement_utilisateur = user_subscription

    amount_paid = Decimal(_value(invoice, "amount_paid")) / Decimal("100")
    invoice_record, created = StripeSubscriptionInvoice.objects.get_or_create(
        stripe_invoice_id=invoice_id,
        defaults={
            "subscription": local_subscription,
            "montant_paye": amount_paid,
            "devise": local_subscription.devise,
            "period_start": period_start,
            "period_end": period_end,
            "raw_response": {
                "invoice_id": invoice_id,
                "subscription_id": provider_subscription_id,
                "status": _value(invoice, "status"),
            },
        },
    )
    if (
        invoice_record.subscription_id != local_subscription.pk
        or invoice_record.montant_paye != amount_paid
        or invoice_record.devise != local_subscription.devise
        or invoice_record.period_start != period_start
        or invoice_record.period_end != period_end
    ):
        raise SubscriptionWebhookMismatch
    if not invoice_record.revenu_id:
        revenue = Revenu.objects.create(type="SUB", montant=amount_paid)
        invoice_record.revenu = revenue
        invoice_record.save(update_fields=["revenu"])
    else:
        revenue = Revenu.objects.select_for_update().get(
            pk=invoice_record.revenu_id
        )
        if revenue.type != "SUB" or revenue.montant != amount_paid:
            raise SubscriptionWebhookMismatch

    if period_start is not None:
        local_subscription.current_period_start = period_start
        local_subscription.current_period_end = period_end
    local_subscription.status = "ACTIVE"
    local_subscription.raw_response = {
        "stage": "invoice_paid",
        "invoice_id": invoice_id,
        "subscription_id": provider_subscription_id,
        "invoice_created": created,
    }
    local_subscription.save(
        update_fields=[
            "stripe_subscription_id",
            "stripe_customer_id",
            "abonnement_utilisateur",
            "current_period_start",
            "current_period_end",
            "status",
            "raw_response",
            "updated_at",
        ]
    )
    return True


def _handle_invoice_payment_failed(invoice):
    metadata = _metadata(invoice)
    provider_subscription_id = _subscription_id_from_invoice(invoice)
    local_subscription = _find_local_subscription(
        provider_subscription_id,
        metadata,
    )
    if local_subscription is None:
        return False
    if not provider_subscription_id:
        raise SubscriptionWebhookMismatch
    invoice_id = _validate_invoice(local_subscription, invoice, "amount_due")
    if not local_subscription.stripe_subscription_id:
        local_subscription.stripe_subscription_id = provider_subscription_id
    if local_subscription.status not in ("CANCELED", "FAILED"):
        local_subscription.status = "PAST_DUE"
    local_subscription.raw_response = {
        "stage": "invoice_payment_failed",
        "invoice_id": invoice_id,
        "subscription_id": provider_subscription_id,
    }
    local_subscription.save(
        update_fields=[
            "stripe_subscription_id",
            "status",
            "raw_response",
            "updated_at",
        ]
    )
    return True


def _validate_subscription_object(local_subscription, subscription):
    provider_subscription_id = _provider_id(subscription)
    price_id = _price_id(subscription)
    if (
        not provider_subscription_id
        or price_id != local_subscription.stripe_price_id
        or (
            local_subscription.stripe_subscription_id
            and provider_subscription_id
            != local_subscription.stripe_subscription_id
        )
    ):
        raise SubscriptionWebhookMismatch
    customer_id = _provider_id(_value(subscription, "customer"))
    if (
        customer_id
        and local_subscription.stripe_customer_id
        and customer_id != local_subscription.stripe_customer_id
    ):
        raise SubscriptionWebhookMismatch
    if not local_subscription.stripe_subscription_id:
        local_subscription.stripe_subscription_id = provider_subscription_id
    return provider_subscription_id, customer_id


def _handle_subscription_updated(subscription):
    metadata = _metadata(subscription)
    provider_subscription_id = _provider_id(subscription)
    local_subscription = _find_local_subscription(
        provider_subscription_id,
        metadata,
    )
    if local_subscription is None:
        return False
    _, customer_id = _validate_subscription_object(
        local_subscription,
        subscription,
    )
    period_start, period_end = _subscription_period(subscription)
    provider_status = str(_value(subscription, "status") or "")
    status_mapping = {
        "past_due": "PAST_DUE",
        "unpaid": "PAST_DUE",
        "canceled": "CANCELED",
        "incomplete_expired": "FAILED",
    }
    if provider_status in status_mapping:
        local_subscription.status = status_mapping[provider_status]
    # An update marked active never grants or extends access without invoice.paid.
    local_subscription.stripe_customer_id = (
        customer_id or local_subscription.stripe_customer_id
    )
    if period_start is not None:
        local_subscription.current_period_start = period_start
        local_subscription.current_period_end = period_end
    local_subscription.cancel_at_period_end = bool(
        _value(subscription, "cancel_at_period_end")
    )
    local_subscription.raw_response = {
        "stage": "subscription_updated",
        "subscription_id": provider_subscription_id,
        "provider_status": provider_status,
    }
    local_subscription.save(
        update_fields=[
            "stripe_subscription_id",
            "stripe_customer_id",
            "current_period_start",
            "current_period_end",
            "cancel_at_period_end",
            "status",
            "raw_response",
            "updated_at",
        ]
    )
    return True


def _handle_subscription_deleted(subscription):
    metadata = _metadata(subscription)
    provider_subscription_id = _provider_id(subscription)
    local_subscription = _find_local_subscription(
        provider_subscription_id,
        metadata,
    )
    if local_subscription is None:
        return False
    _, customer_id = _validate_subscription_object(
        local_subscription,
        subscription,
    )
    period_start, period_end = _subscription_period(subscription)
    local_subscription.status = "CANCELED"
    local_subscription.stripe_customer_id = (
        customer_id or local_subscription.stripe_customer_id
    )
    if period_start is not None:
        local_subscription.current_period_start = period_start
        local_subscription.current_period_end = period_end
    local_subscription.cancel_at_period_end = bool(
        _value(subscription, "cancel_at_period_end")
    )
    local_subscription.raw_response = {
        "stage": "subscription_deleted",
        "subscription_id": provider_subscription_id,
    }
    if local_subscription.abonnement_utilisateur_id:
        user_subscription = AbonnementUtilisateur.objects.select_for_update().get(
            pk=local_subscription.abonnement_utilisateur_id
        )
        user_subscription.actif = False
        user_subscription.save(update_fields=["actif"])
    local_subscription.save(
        update_fields=[
            "stripe_subscription_id",
            "stripe_customer_id",
            "current_period_start",
            "current_period_end",
            "cancel_at_period_end",
            "status",
            "raw_response",
            "updated_at",
        ]
    )
    return True


SUBSCRIPTION_EVENT_HANDLERS = {
    "checkout.session.completed": _handle_checkout_completed,
    "invoice.paid": _handle_invoice_paid,
    "invoice.payment_failed": _handle_invoice_payment_failed,
    "customer.subscription.updated": _handle_subscription_updated,
    "customer.subscription.deleted": _handle_subscription_deleted,
}


def process_subscription_event(event):
    """Process one signed Stripe event exactly once after a successful transition."""
    event_type = str(_value(event, "type") or "")
    if event_type not in SUBSCRIPTION_EVENT_TYPES:
        return False
    event_id = str(_value(event, "id") or "")
    if not event_id:
        raise SubscriptionWebhookMismatch
    event_object = _path(event, "data", "object")
    if event_object is None:
        raise SubscriptionWebhookMismatch

    try:
        with transaction.atomic():
            if StripeWebhookEvent.objects.filter(
                stripe_event_id=event_id
            ).exists():
                return True
            handled = SUBSCRIPTION_EVENT_HANDLERS[event_type](event_object)
            StripeWebhookEvent.objects.create(
                stripe_event_id=event_id,
                event_type=event_type,
                processed_at=timezone.now(),
            )
            return handled
    except IntegrityError:
        if StripeWebhookEvent.objects.filter(stripe_event_id=event_id).exists():
            return True
        raise
