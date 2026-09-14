import uuid
from urllib.parse import quote_plus

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


HISTORICAL_EVENT_NAMESPACE = uuid.UUID("b27941f1-e772-4ab8-a981-5df03f8b922f")
BATCH_SIZE = 500


def historical_event_key(order_id):
    return uuid.uuid5(
        HISTORICAL_EVENT_NAMESPACE,
        f"order-fulfillment-history:{order_id}",
    )


def tracking_url(carrier, tracking_number):
    carrier_name = (carrier or "").strip().lower()
    tracking = (tracking_number or "").strip()
    if not tracking:
        return ""
    encoded = quote_plus(tracking)
    if "dhl" in carrier_name:
        return (
            "https://www.dhl.de/de/privatkunden/"
            f"dhl-sendungsverfolgung.html?piececode={encoded}"
        )
    if "ups" in carrier_name:
        return f"https://www.ups.com/track?loc=de_DE&tracknum={encoded}"
    if "deutsche post" in carrier_name or carrier_name in {
        "post",
        "deutschepost",
    }:
        return "https://www.deutschepost.de/de/s/sendungsverfolgung.html"
    return ""


def create_historical_fulfillment_events(apps, schema_editor):
    database = schema_editor.connection.alias
    Commande = apps.get_model("shop", "Commande")
    OrderFulfillmentEvent = apps.get_model("shop", "OrderFulfillmentEvent")
    batch = []
    orders = Commande.objects.using(database).order_by("pk").iterator(
        chunk_size=BATCH_SIZE
    )
    for order in orders:
        batch.append(
            OrderFulfillmentEvent(
                commande_id=order.pk,
                old_status=order.fulfillment_status,
                new_status=order.fulfillment_status,
                actor_id=None,
                created_at=order.date_commande,
                note="État historique importé",
                carrier=order.carrier or "",
                tracking_number=order.tracking_number or "",
                tracking_url=tracking_url(order.carrier, order.tracking_number),
                idempotency_key=historical_event_key(order.pk),
            )
        )
        if len(batch) == BATCH_SIZE:
            OrderFulfillmentEvent.objects.using(database).bulk_create(batch)
            batch = []
    if batch:
        OrderFulfillmentEvent.objects.using(database).bulk_create(batch)


def remove_historical_fulfillment_events(apps, schema_editor):
    database = schema_editor.connection.alias
    Commande = apps.get_model("shop", "Commande")
    OrderFulfillmentEvent = apps.get_model("shop", "OrderFulfillmentEvent")
    keys = []
    order_ids = Commande.objects.using(database).order_by("pk").values_list(
        "pk", flat=True
    )
    for order_id in order_ids.iterator(chunk_size=BATCH_SIZE):
        keys.append(historical_event_key(order_id))
        if len(keys) == BATCH_SIZE:
            OrderFulfillmentEvent.objects.using(database).filter(
                idempotency_key__in=keys
            ).delete()
            keys = []
    if keys:
        OrderFulfillmentEvent.objects.using(database).filter(
            idempotency_key__in=keys
        ).delete()


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("shop", "0023_order_cancellation_integrity"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrderFulfillmentEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "old_status",
                    models.CharField(
                        choices=[
                            ("WAITING_PAYMENT", "En attente de paiement"),
                            ("TO_PREPARE", "À préparer"),
                            ("PREPARING", "En préparation"),
                            ("SHIPPED", "Expédiée"),
                            ("DELIVERED", "Livrée"),
                            ("CANCELED", "Traitement annulé"),
                        ],
                        editable=False,
                        max_length=20,
                        verbose_name="Ancien statut",
                    ),
                ),
                (
                    "new_status",
                    models.CharField(
                        choices=[
                            ("WAITING_PAYMENT", "En attente de paiement"),
                            ("TO_PREPARE", "À préparer"),
                            ("PREPARING", "En préparation"),
                            ("SHIPPED", "Expédiée"),
                            ("DELIVERED", "Livrée"),
                            ("CANCELED", "Traitement annulé"),
                        ],
                        editable=False,
                        max_length=20,
                        verbose_name="Nouveau statut",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                (
                    "note",
                    models.TextField(
                        blank=True,
                        editable=False,
                        max_length=1000,
                        verbose_name="Note opérationnelle",
                    ),
                ),
                (
                    "carrier",
                    models.CharField(
                        blank=True,
                        editable=False,
                        max_length=100,
                        verbose_name="Transporteur",
                    ),
                ),
                (
                    "tracking_number",
                    models.CharField(
                        blank=True,
                        editable=False,
                        max_length=150,
                        verbose_name="Numéro de suivi",
                    ),
                ),
                (
                    "tracking_url",
                    models.URLField(
                        blank=True,
                        editable=False,
                        max_length=500,
                        verbose_name="URL de suivi",
                    ),
                ),
                (
                    "idempotency_key",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        unique=True,
                        verbose_name="Clé d’idempotence",
                    ),
                ),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="fulfillment_events",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Acteur staff",
                    ),
                ),
                (
                    "commande",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="fulfillment_events",
                        to="shop.commande",
                        verbose_name="Commande",
                    ),
                ),
            ],
            options={
                "verbose_name": "Événement logistique",
                "verbose_name_plural": "Événements logistiques",
                "ordering": ("created_at", "pk"),
            },
        ),
        migrations.AddIndex(
            model_name="orderfulfillmentevent",
            index=models.Index(
                fields=["commande", "created_at"],
                name="shop_fulfi_command_1d5f54_idx",
            ),
        ),
        migrations.RunPython(
            create_historical_fulfillment_events,
            remove_historical_fulfillment_events,
        ),
    ]
