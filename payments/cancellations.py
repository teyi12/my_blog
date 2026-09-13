import logging
from dataclasses import dataclass

import stripe
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from shop.inventory import release_order_stock
from shop.models import Commande, OrderCancellation

from .models import Payment


logger = logging.getLogger(__name__)


class OrderCancellationNotAllowed(Exception):
    pass


class PaidOrderCancellationNotAllowed(OrderCancellationNotAllowed):
    pass


@dataclass(frozen=True)
class CancellationOutcome:
    cancellation: OrderCancellation
    created: bool


def order_can_be_canceled(order):
    return (
        order.payment_status in {"PENDING", "PROCESSING", "FAILED", "CANCELED"}
        and order.fulfillment_status not in {"SHIPPED", "DELIVERED"}
        and not OrderCancellation.objects.filter(commande_id=order.pk).exists()
    )


def _check_actor(order, actor, source):
    if actor is None or not actor.is_authenticated:
        raise PermissionDenied
    if source == "STAFF":
        if not actor.is_staff:
            raise PermissionDenied
        return
    if source == "CUSTOMER" and actor.pk == order.client_id:
        return
    raise PermissionDenied


def _schedule_cancellation_notification(cancellation_id):
    transaction.on_commit(
        lambda: send_order_cancellation_notification(cancellation_id)
    )


def _cancel_order_locally(order_id, actor, source):
    with transaction.atomic():
        order = (
            Commande.objects.select_for_update()
            .select_related("client")
            .get(pk=order_id)
        )
        _check_actor(order, actor, source)

        existing = OrderCancellation.objects.filter(commande=order).first()
        if existing is not None:
            return existing, False, None

        payments = list(
            Payment.objects.select_for_update()
            .filter(commande=order)
            .order_by("pk")
        )
        if order.payment_status == "SUCCESS" or any(
            payment.status == "SUCCESS" for payment in payments
        ):
            raise PaidOrderCancellationNotAllowed
        if (
            order.payment_status == "REFUNDED"
            or order.fulfillment_status in {"SHIPPED", "DELIVERED"}
        ):
            raise OrderCancellationNotAllowed
        if order.payment_status not in {
            "PENDING",
            "PROCESSING",
            "FAILED",
            "CANCELED",
        }:
            raise OrderCancellationNotAllowed

        stripe_payment = next(
            (
                payment
                for payment in payments
                if payment.channel == "STRIPE"
                and payment.status == "PROCESSING"
                and payment.transaction_id.startswith("cs_")
            ),
            None,
        )
        expiration_status = "PENDING" if stripe_payment else "NOT_REQUIRED"

        for payment in payments:
            if payment.status in {"PENDING", "PROCESSING"}:
                payment.status = "CANCELED"
                payment.save(update_fields=["status", "updated_at"])

        release_order_stock(order.pk)
        order.payment_status = "CANCELED"
        order.fulfillment_status = "CANCELED"
        order.save(update_fields=["payment_status", "fulfillment_status"])
        cancellation = OrderCancellation.objects.create(
            commande=order,
            requested_by=actor,
            source=source,
            stripe_expiration_status=expiration_status,
        )
        _schedule_cancellation_notification(cancellation.pk)
        return cancellation, True, stripe_payment.pk if stripe_payment else None


def _expire_stripe_session_once(cancellation_id, payment_id):
    with transaction.atomic():
        cancellation = OrderCancellation.objects.select_for_update().get(
            pk=cancellation_id
        )
        if cancellation.stripe_expiration_status != "PENDING":
            return cancellation
        cancellation.stripe_expiration_status = "PROCESSING"
        cancellation.stripe_expiration_attempted_at = timezone.now()
        cancellation.save(
            update_fields=[
                "stripe_expiration_status",
                "stripe_expiration_attempted_at",
            ]
        )

    payment = Payment.objects.only("transaction_id").get(pk=payment_id)
    try:
        expired_session = stripe.checkout.Session.expire(
            payment.transaction_id,
            idempotency_key=str(cancellation.idempotency_key),
        )
        succeeded = getattr(expired_session, "status", None) == "expired"
        if isinstance(expired_session, dict):
            succeeded = expired_session.get("status") == "expired"
    except Exception as exc:
        logger.warning(
            "operation=order_cancellation_stripe_expiration "
            "exception_type=%s order_id=%s cancellation_id=%s",
            type(exc).__name__,
            cancellation.commande_id,
            cancellation.pk,
        )
        succeeded = False

    with transaction.atomic():
        cancellation = OrderCancellation.objects.select_for_update().get(
            pk=cancellation_id
        )
        if cancellation.stripe_expiration_status == "PROCESSING":
            cancellation.stripe_expiration_status = (
                "SUCCEEDED" if succeeded else "FAILED"
            )
            cancellation.save(update_fields=["stripe_expiration_status"])
        return cancellation


def cancel_order(order_id, actor, source):
    cancellation, created, payment_id = _cancel_order_locally(
        order_id,
        actor,
        source,
    )
    if payment_id is None and cancellation.stripe_expiration_status == "PENDING":
        payment_id = (
            Payment.objects.filter(
                commande_id=order_id,
                channel="STRIPE",
                transaction_id__startswith="cs_",
            )
            .order_by("pk")
            .values_list("pk", flat=True)
            .first()
        )
    if payment_id is not None:
        cancellation = _expire_stripe_session_once(cancellation.pk, payment_id)
    return CancellationOutcome(cancellation=cancellation, created=created)


def _customer_order_url(order):
    path = reverse("shop:ma_commande_detail", kwargs={"pk": order.pk})
    base_url = getattr(settings, "SITE_BASE_URL", "").strip().rstrip("/")
    return f"{base_url}{path}" if base_url else ""


def send_order_cancellation_notification(cancellation_id):
    cancellation = (
        OrderCancellation.objects.select_related("commande__client")
        .filter(pk=cancellation_id, notification_sent_at__isnull=True)
        .first()
    )
    if cancellation is None:
        return False
    order = cancellation.commande
    recipient = (order.client.email or "").strip()
    sender = (
        getattr(settings, "DEFAULT_FROM_EMAIL", "").strip()
        or getattr(settings, "EMAIL_HOST_USER", "").strip()
    )
    if not recipient or not sender:
        return False

    with translation.override(order.language_code or "fr"):
        subject = _("Votre commande #%(order)s a été annulée") % {
            "order": order.pk
        }
        customer_name = order.client.first_name or _("cher client")
        detail_url = _customer_order_url(order)
        body_lines = [
            _("Bonjour %(name)s,") % {"name": customer_name},
            "",
            _("Votre commande #%(order)s a bien été annulée.")
            % {"order": order.pk},
            _("Aucun paiement ne sera initié pour cette commande."),
        ]
        if detail_url:
            body_lines.extend(
                ["", _("Consulter votre commande : %(url)s") % {"url": detail_url}]
            )
        body_lines.extend(["", _("L'équipe My Blog Shop")])
        html_body = render_to_string(
            "shop/emails/order_canceled.html",
            {
                "subject": subject,
                "commande": order,
                "customer_name": customer_name,
                "detail_url": detail_url,
                "email_language": order.language_code or "fr",
            },
        )
        try:
            message = EmailMultiAlternatives(
                subject=subject,
                body="\n".join(body_lines),
                from_email=sender,
                to=[recipient],
            )
            message.attach_alternative(html_body, "text/html")
            message.send(fail_silently=False)
        except Exception as exc:
            logger.warning(
                "operation=order_cancellation_notification "
                "exception_type=%s order_id=%s cancellation_id=%s",
                type(exc).__name__,
                order.pk,
                cancellation.pk,
            )
            return False

    with transaction.atomic():
        locked = OrderCancellation.objects.select_for_update().get(
            pk=cancellation.pk
        )
        if locked.notification_sent_at is None:
            locked.notification_sent_at = timezone.now()
            locked.save(update_fields=["notification_sent_at"])
    return True
