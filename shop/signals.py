from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Commande
from .shipping import send_fulfillment_notification


@receiver(pre_save, sender=Commande)
def remember_previous_fulfillment_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_fulfillment_status = None
        return
    instance._previous_fulfillment_status = (
        sender.objects.filter(pk=instance.pk)
        .values_list("fulfillment_status", flat=True)
        .first()
    )


@receiver(post_save, sender=Commande)
def notify_customer_of_fulfillment_change(sender, instance, created, **kwargs):
    if created:
        return
    previous = getattr(instance, "_previous_fulfillment_status", None)
    current = instance.fulfillment_status
    if current == previous or current not in {"SHIPPED", "DELIVERED"}:
        return

    order_id = instance.pk

    def send_after_commit():
        try:
            order = sender.objects.select_related("client").get(pk=order_id)
        except sender.DoesNotExist:
            return
        send_fulfillment_notification(order, current)

    transaction.on_commit(send_after_commit)
