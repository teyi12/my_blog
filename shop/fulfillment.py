from django.db import transaction
from django.utils import timezone

from .models import Commande


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


def _clean_shipping_details(carrier, tracking_number):
    carrier = (carrier or "").strip()
    tracking_number = (tracking_number or "").strip()
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


def transition_order_fulfillment(
    order_id,
    new_status,
    *,
    carrier="",
    tracking_number="",
):
    """Apply one authorized fulfillment transition to a locked paid order."""
    with transaction.atomic():
        order = Commande.objects.select_for_update().get(pk=order_id)
        if order.payment_status != "SUCCESS":
            raise PaymentNotConfirmed
        if new_status not in order.allowed_fulfillment_transitions():
            raise InvalidFulfillmentTransition

        update_fields = ["fulfillment_status"]
        order.fulfillment_status = new_status
        now = timezone.now()

        if new_status == "SHIPPED":
            order.carrier, order.tracking_number = _clean_shipping_details(
                carrier,
                tracking_number,
            )
            order.shipped_at = now
            update_fields.extend(["carrier", "tracking_number", "shipped_at"])
        elif new_status == "DELIVERED":
            _clean_shipping_details(order.carrier, order.tracking_number)
            order.delivered_at = now
            update_fields.append("delivered_at")

        order.save(update_fields=update_fields)
        return order


def update_order_shipping_details(order_id, *, carrier, tracking_number):
    """Update tracking data without changing payment or fulfillment status."""
    carrier, tracking_number = _clean_shipping_details(carrier, tracking_number)
    with transaction.atomic():
        order = Commande.objects.select_for_update().get(pk=order_id)
        if order.payment_status != "SUCCESS":
            raise PaymentNotConfirmed
        if order.fulfillment_status not in {"SHIPPED", "DELIVERED"}:
            raise ShippingDetailsNotEditable

        order.carrier = carrier
        order.tracking_number = tracking_number
        order.save(update_fields=["carrier", "tracking_number"])
        return order
