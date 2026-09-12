import logging
import smtplib

import stripe
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from shop.models import Commande

from .models import Payment, StripeOrderRefund, StripeWebhookEvent
from .money import minor_amount


logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY

REFUND_EVENT_TYPES = {"refund.created", "refund.updated", "refund.failed"}
PROVIDER_PENDING_STATUSES = {"pending", "requires_action"}
PROVIDER_TERMINAL_STATUSES = {"failed", "canceled"}


class RefundNotAllowed(Exception):
    pass


class RefundInProgress(Exception):
    pass


class RefundAlreadyCompleted(Exception):
    pass


class RefundProviderError(Exception):
    pass


class RefundMismatch(Exception):
    pass


class RefundWebhookRetry(Exception):
    pass


def _value(value, key):
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _provider_id(value):
    if isinstance(value, str):
        return value
    return str(_value(value, "id") or "")


def _metadata(value):
    metadata = _value(value, "metadata") or {}
    return metadata if isinstance(metadata, (dict, stripe.StripeObject)) else {}


def _local_payment_matches(order, payment):
    return (
        order.payment_status == "SUCCESS"
        and order.payment_channel == "STRIPE"
        and payment.commande_id == order.id
        and payment.channel == "STRIPE"
        and payment.status == "SUCCESS"
        and payment.transaction_id.startswith("cs_")
        and order.transaction_id == payment.transaction_id
        and payment.montant == order.total
        and payment.devise.upper() == order.currency.upper()
    )


def get_refundable_payment(order):
    if order.payment_status != "SUCCESS" or order.payment_channel != "STRIPE":
        return None
    payment = (
        Payment.objects.filter(
            commande=order,
            channel="STRIPE",
            status="SUCCESS",
            transaction_id=order.transaction_id,
        )
        .order_by("pk")
        .first()
    )
    if payment is None or not _local_payment_matches(order, payment):
        return None
    return payment


def _claim_refund(order_id, requested_by_id):
    with transaction.atomic():
        order = Commande.objects.select_for_update().get(pk=order_id)
        if order.payment_status == "REFUNDED":
            raise RefundAlreadyCompleted
        if order.payment_status != "SUCCESS" or order.payment_channel != "STRIPE":
            raise RefundNotAllowed

        payment = (
            Payment.objects.select_for_update()
            .filter(
                commande=order,
                channel="STRIPE",
                status="SUCCESS",
                transaction_id=order.transaction_id,
            )
            .first()
        )
        if payment is None or not _local_payment_matches(order, payment):
            raise RefundNotAllowed

        refund = (
            StripeOrderRefund.objects.select_for_update()
            .filter(commande=order)
            .first()
        )
        if refund is None:
            refund = StripeOrderRefund.objects.create(
                commande=order,
                payment=payment,
                requested_by_id=requested_by_id,
                montant=payment.montant,
                devise=payment.devise.upper(),
                status="PROCESSING",
            )
            return refund

        if (
            refund.payment_id != payment.id
            or refund.montant != payment.montant
            or refund.devise.upper() != payment.devise.upper()
        ):
            raise RefundMismatch
        if refund.status == "SUCCESS":
            raise RefundAlreadyCompleted
        if refund.status in {"PROCESSING", "PENDING"}:
            raise RefundInProgress
        if refund.status != "RETRYABLE":
            raise RefundNotAllowed

        refund.status = "PROCESSING"
        refund.save(update_fields=["status", "updated_at"])
        return refund


def _checkout_payment_intent(refund, session):
    order = refund.commande
    payment = refund.payment
    metadata = _metadata(session)
    payment_intent_id = _provider_id(_value(session, "payment_intent"))
    if (
        not _local_payment_matches(order, payment)
        or _provider_id(session) != payment.transaction_id
        or _value(session, "payment_status") != "paid"
        or _value(session, "status") != "complete"
        or _value(session, "amount_total")
        != minor_amount(refund.montant, refund.devise)
        or str(_value(session, "currency") or "").upper()
        != refund.devise.upper()
        or str(_value(metadata, "commande_id") or "") != str(order.id)
        or str(_value(metadata, "payment_id") or "") != str(payment.id)
        or str(_value(metadata, "user_id") or "") != str(order.client_id)
        or not payment_intent_id.startswith("pi_")
        or (
            refund.stripe_payment_intent_id
            and refund.stripe_payment_intent_id != payment_intent_id
        )
    ):
        raise RefundMismatch
    return payment_intent_id


def _store_payment_intent(refund_id, payment_intent_id):
    with transaction.atomic():
        refund = StripeOrderRefund.objects.select_for_update().get(pk=refund_id)
        if refund.status != "PROCESSING":
            raise RefundInProgress
        if (
            refund.stripe_payment_intent_id
            and refund.stripe_payment_intent_id != payment_intent_id
        ):
            raise RefundMismatch
        if not refund.stripe_payment_intent_id:
            refund.stripe_payment_intent_id = payment_intent_id
            refund.save(
                update_fields=["stripe_payment_intent_id", "updated_at"]
            )


def _mark_retryable(refund_id):
    with transaction.atomic():
        refund = StripeOrderRefund.objects.select_for_update().get(pk=refund_id)
        if refund.status == "PROCESSING":
            refund.status = "RETRYABLE"
            refund.save(update_fields=["status", "updated_at"])


def _refund_metadata(refund):
    return {
        "refund_request_id": str(refund.id),
        "commande_id": str(refund.commande_id),
        "payment_id": str(refund.payment_id),
        "user_id": str(refund.commande.client_id),
    }


def _refund_object_matches(refund, provider_refund):
    metadata = _metadata(provider_refund)
    provider_refund_id = _provider_id(provider_refund)
    payment_intent_id = _provider_id(_value(provider_refund, "payment_intent"))
    return (
        provider_refund_id.startswith("re_")
        and payment_intent_id == refund.stripe_payment_intent_id
        and _value(provider_refund, "amount")
        == minor_amount(refund.montant, refund.devise)
        and str(_value(provider_refund, "currency") or "").upper()
        == refund.devise.upper()
        and str(_value(metadata, "refund_request_id") or "") == str(refund.id)
        and str(_value(metadata, "commande_id") or "")
        == str(refund.commande_id)
        and str(_value(metadata, "payment_id") or "") == str(refund.payment_id)
        and str(_value(metadata, "user_id") or "")
        == str(refund.commande.client_id)
        and (
            not refund.stripe_refund_id
            or refund.stripe_refund_id == provider_refund_id
        )
    )


def _schedule_refund_notification(order_id):
    def notify_after_commit():
        try:
            order = Commande.objects.select_related("client").get(pk=order_id)
        except Commande.DoesNotExist:
            return
        send_refund_notification(order)

    transaction.on_commit(notify_after_commit)


def _apply_provider_refund(refund_id, provider_refund):
    refund_info = StripeOrderRefund.objects.only(
        "commande_id", "payment_id"
    ).get(pk=refund_id)
    with transaction.atomic():
        order = Commande.objects.select_for_update().get(
            pk=refund_info.commande_id
        )
        payment = Payment.objects.select_for_update().get(
            pk=refund_info.payment_id,
            commande=order,
        )
        refund = (
            StripeOrderRefund.objects.select_for_update()
            .select_related("commande")
            .get(pk=refund_id, commande=order, payment=payment)
        )
        if (
            payment.channel != "STRIPE"
            or payment.status != "SUCCESS"
            or payment.transaction_id != order.transaction_id
            or payment.montant != refund.montant
            or payment.devise.upper() != refund.devise.upper()
            or order.total != refund.montant
            or order.currency.upper() != refund.devise.upper()
            or order.payment_status not in {"SUCCESS", "REFUNDED"}
            or not _refund_object_matches(refund, provider_refund)
        ):
            raise RefundMismatch

        provider_status = str(_value(provider_refund, "status") or "")
        if provider_status not in (
            {"succeeded"} | PROVIDER_PENDING_STATUSES | PROVIDER_TERMINAL_STATUSES
        ):
            raise RefundMismatch

        if refund.status == "SUCCESS":
            return refund
        if (
            refund.status in {"FAILED", "CANCELED"}
            and provider_status != "succeeded"
        ):
            return refund

        refund.stripe_refund_id = _provider_id(provider_refund)
        update_fields = ["stripe_refund_id", "status", "updated_at"]
        if provider_status == "succeeded":
            refund.status = "SUCCESS"
            refund.confirmed_at = timezone.now()
            update_fields.append("confirmed_at")
            order.payment_status = "REFUNDED"
            order.save(update_fields=["payment_status"])
            _schedule_refund_notification(order.id)
        elif provider_status in PROVIDER_PENDING_STATUSES:
            refund.status = "PENDING"
        elif provider_status == "failed":
            refund.status = "FAILED"
        else:
            refund.status = "CANCELED"
        refund.save(update_fields=update_fields)
        return refund


def request_full_refund(order_id, requested_by_id):
    refund = _claim_refund(order_id, requested_by_id)
    try:
        session = stripe.checkout.Session.retrieve(refund.payment.transaction_id)
    except (stripe.StripeError, OSError):
        _mark_retryable(refund.id)
        raise RefundProviderError from None

    try:
        payment_intent_id = _checkout_payment_intent(refund, session)
        _store_payment_intent(refund.id, payment_intent_id)
    except RefundMismatch:
        _mark_failed(refund.id)
        raise

    try:
        provider_refund = stripe.Refund.create(
            payment_intent=payment_intent_id,
            amount=minor_amount(refund.montant, refund.devise),
            metadata=_refund_metadata(refund),
            idempotency_key=str(refund.idempotency_key),
        )
    except (stripe.StripeError, OSError):
        _mark_retryable(refund.id)
        raise RefundProviderError from None
    try:
        return _apply_provider_refund(refund.id, provider_refund)
    except RefundMismatch:
        _mark_failed(refund.id)
        raise


def _mark_failed(refund_id):
    with transaction.atomic():
        refund = StripeOrderRefund.objects.select_for_update().get(pk=refund_id)
        if refund.status == "PROCESSING":
            refund.status = "FAILED"
            refund.save(update_fields=["status", "updated_at"])


def process_refund_event(event):
    event_type = str(_value(event, "type") or "")
    if event_type not in REFUND_EVENT_TYPES:
        return False
    event_id = _provider_id(event)
    provider_refund = _value(_value(event, "data") or {}, "object")
    metadata = _metadata(provider_refund)
    local_refund_id = str(_value(metadata, "refund_request_id") or "")
    if not event_id or provider_refund is None or not local_refund_id.isdigit():
        raise RefundMismatch

    try:
        with transaction.atomic():
            if StripeWebhookEvent.objects.filter(
                stripe_event_id=event_id
            ).exists():
                return True
            refund = StripeOrderRefund.objects.filter(pk=local_refund_id).first()
            if refund is None:
                raise RefundWebhookRetry
            _apply_provider_refund(refund.id, provider_refund)
            StripeWebhookEvent.objects.create(
                stripe_event_id=event_id,
                event_type=event_type,
                processed_at=timezone.now(),
            )
            return True
    except IntegrityError:
        if StripeWebhookEvent.objects.filter(stripe_event_id=event_id).exists():
            return True
        raise


def _customer_order_url(order):
    path = reverse("shop:ma_commande_detail", kwargs={"pk": order.pk})
    base_url = getattr(settings, "SITE_BASE_URL", "").strip().rstrip("/")
    return f"{base_url}{path}" if base_url else ""


def send_refund_notification(order):
    recipient = (order.client.email or "").strip()
    sender = getattr(settings, "DEFAULT_FROM_EMAIL", "").strip()
    if not recipient or not sender:
        return False

    with translation.override(order.language_code or "fr"):
        subject = _("Votre commande #%(order)s a été remboursée") % {
            "order": order.pk
        }
        detail_url = _customer_order_url(order)
        body = _(
            "Le remboursement total de %(amount)s %(currency)s a été confirmé."
        ) % {"amount": order.total, "currency": order.currency}
        html_body = render_to_string(
            "payments/emails/order_refunded.html",
            {
                "subject": subject,
                "commande": order,
                "detail_url": detail_url,
            },
        )

        try:
            message = EmailMultiAlternatives(
                subject=subject,
                body="\n\n".join(
                    part
                    for part in (
                        body,
                        _("Consulter votre commande : %(url)s")
                        % {"url": detail_url}
                        if detail_url
                        else "",
                    )
                    if part
                ),
                from_email=sender,
                to=[recipient],
            )
            message.attach_alternative(html_body, "text/html")
            message.send(fail_silently=False)
        except (smtplib.SMTPException, OSError) as exc:
            logger.warning(
                "operation=order_refund_notification exception_type=%s order_id=%s",
                type(exc).__name__,
                order.pk,
            )
            return False
    return True
