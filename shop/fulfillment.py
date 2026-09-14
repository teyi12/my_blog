import uuid

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .models import Commande, OrderCancellation, OrderFulfillmentEvent
from .shipping import carrier_tracking_url, send_fulfillment_event_notification


class FulfillmentError(Exception):
    """Base class for an expected fulfillment workflow rejection."""


class PaymentNotConfirmed(FulfillmentError):
    pass


class InvalidFulfillmentTransition(FulfillmentError):
    pass


class ShippingDetailsInvalid(FulfillmentError):
    pass


class ShippingDetailsNotEditable(FulfillmentError):
    pass


class FulfillmentIdempotencyConflict(FulfillmentError):
    pass


def _check_staff(actor):
    if actor is None or not actor.is_authenticated or not actor.is_staff:
        raise PermissionDenied


def _clean_note(note):
    normalized = (note or "").strip()
    max_length = OrderFulfillmentEvent._meta.get_field("note").max_length
    if len(normalized) > max_length:
        raise InvalidFulfillmentTransition
    return normalized


def _clean_shipping_details(carrier, tracking_number):
    carrier = " ".join((carrier or "").split())
    tracking_number = " ".join((tracking_number or "").split())
    carrier_max_length = Commande._meta.get_field("carrier").max_length
    tracking_max_length = Commande._meta.get_field("tracking_number").max_length
    if (
        not carrier
        or not tracking_number
        or len(carrier) > carrier_max_length
        or len(tracking_number) > tracking_max_length
    ):
        raise ShippingDetailsInvalid
    return carrier, tracking_number


def _idempotency_key(value):
    if not value:
        return uuid.uuid4()
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise FulfillmentIdempotencyConflict from exc


def _existing_idempotent_event(order, key, new_status):
    event = OrderFulfillmentEvent.objects.filter(idempotency_key=key).first()
    if event is None:
        return None
    if event.commande_id != order.pk or event.new_status != new_status:
        raise FulfillmentIdempotencyConflict
    return event


def _schedule_notification(event):
    if event.new_status not in {"SHIPPED", "DELIVERED"}:
        return
    transaction.on_commit(
        lambda event_id=event.pk: send_fulfillment_event_notification(event_id)
    )


def allowed_order_fulfillment_transitions(order):
    if order.payment_status != "SUCCESS":
        return set()
    if OrderCancellation.objects.filter(commande_id=order.pk).exists():
        return set()
    return order.allowed_fulfillment_transitions()


def record_system_fulfillment_event(
    order,
    old_status,
    new_status,
    *,
    action,
    actor=None,
    note="",
):
    """Append an idempotent event for an existing transactional workflow."""
    key = uuid.uuid5(
        uuid.UUID("46613f2a-7186-4bed-bb0f-b659791d243d"),
        f"{action}:{order.pk}",
    )
    event, _created = OrderFulfillmentEvent.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "commande": order,
            "old_status": old_status,
            "new_status": new_status,
            "actor": actor,
            "note": _clean_note(note),
            "carrier": order.carrier if new_status in {"SHIPPED", "DELIVERED"} else "",
            "tracking_number": (
                order.tracking_number
                if new_status in {"SHIPPED", "DELIVERED"}
                else ""
            ),
            "tracking_url": (
                carrier_tracking_url(order.carrier, order.tracking_number)
                if new_status in {"SHIPPED", "DELIVERED"}
                else ""
            ),
        },
    )
    if (
        event.commande_id != order.pk
        or event.old_status != old_status
        or event.new_status != new_status
    ):
        raise FulfillmentIdempotencyConflict
    return event


def transition_order_fulfillment(
    order_id,
    new_status,
    *,
    actor,
    carrier="",
    tracking_number="",
    note="",
    idempotency_key=None,
):
    """Apply one authorized and journaled transition to a locked paid order."""
    _check_staff(actor)
    key = _idempotency_key(idempotency_key)
    note = _clean_note(note)

    with transaction.atomic():
        order = Commande.objects.select_for_update(of=("self",)).get(pk=order_id)
        existing_event = _existing_idempotent_event(order, key, new_status)
        if existing_event is not None:
            return order
        if order.payment_status != "SUCCESS":
            raise PaymentNotConfirmed
        if new_status not in allowed_order_fulfillment_transitions(order):
            raise InvalidFulfillmentTransition

        old_status = order.fulfillment_status
        update_fields = ["fulfillment_status"]
        order.fulfillment_status = new_status
        now = timezone.now()

        if new_status == "SHIPPED":
            if order.is_digital_only:
                raise InvalidFulfillmentTransition
            order.carrier, order.tracking_number = _clean_shipping_details(
                carrier,
                tracking_number,
            )
            order.shipped_at = now
            update_fields.extend(["carrier", "tracking_number", "shipped_at"])
        elif new_status == "DELIVERED":
            if not order.is_digital_only:
                _clean_shipping_details(order.carrier, order.tracking_number)
            order.delivered_at = now
            update_fields.append("delivered_at")

        order.save(update_fields=update_fields)
        event = OrderFulfillmentEvent.objects.create(
            commande=order,
            old_status=old_status,
            new_status=new_status,
            actor=actor,
            note=note,
            carrier=order.carrier if new_status in {"SHIPPED", "DELIVERED"} else "",
            tracking_number=(
                order.tracking_number
                if new_status in {"SHIPPED", "DELIVERED"}
                else ""
            ),
            tracking_url=(
                carrier_tracking_url(order.carrier, order.tracking_number)
                if new_status in {"SHIPPED", "DELIVERED"}
                else ""
            ),
            idempotency_key=key,
        )
        _schedule_notification(event)
        return order


def update_order_shipping_details(
    order_id,
    *,
    actor,
    carrier,
    tracking_number,
    note="",
    idempotency_key=None,
):
    """Update tracking data through the same locked, append-only workflow."""
    _check_staff(actor)
    key = _idempotency_key(idempotency_key)
    note = _clean_note(note)
    carrier, tracking_number = _clean_shipping_details(carrier, tracking_number)

    with transaction.atomic():
        order = Commande.objects.select_for_update(of=("self",)).get(pk=order_id)
        existing_event = _existing_idempotent_event(
            order,
            key,
            order.fulfillment_status,
        )
        if existing_event is not None:
            return order
        if order.payment_status != "SUCCESS":
            raise PaymentNotConfirmed
        if OrderCancellation.objects.filter(commande_id=order.pk).exists():
            raise ShippingDetailsNotEditable
        if order.is_digital_only or order.fulfillment_status not in {
            "SHIPPED",
            "DELIVERED",
        }:
            raise ShippingDetailsNotEditable
        if order.carrier == carrier and order.tracking_number == tracking_number:
            return order

        order.carrier = carrier
        order.tracking_number = tracking_number
        order.save(update_fields=["carrier", "tracking_number"])
        OrderFulfillmentEvent.objects.create(
            commande=order,
            old_status=order.fulfillment_status,
            new_status=order.fulfillment_status,
            actor=actor,
            note=note,
            carrier=carrier,
            tracking_number=tracking_number,
            tracking_url=carrier_tracking_url(carrier, tracking_number),
            idempotency_key=key,
        )
        return order
