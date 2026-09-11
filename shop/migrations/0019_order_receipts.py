from decimal import Decimal
import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


BATCH_SIZE = 200


def decimal_snapshot(value):
    return format(Decimal(value), "f")


def normalize_language(language_code):
    return language_code if language_code in {"fr", "de", "en"} else "fr"


def backfill_paid_order_receipts(apps, schema_editor):
    database = schema_editor.connection.alias
    Commande = apps.get_model("shop", "Commande")
    OrderReceipt = apps.get_model("shop", "OrderReceipt")

    paid_orders = (
        Commande.objects.using(database)
        .filter(payment_status="SUCCESS")
        .select_related("client", "adresse")
        .order_by("pk")
        .iterator(chunk_size=BATCH_SIZE)
    )
    batch = []
    for order in paid_orders:
        customer = order.client
        customer_name = " ".join(
            part.strip()
            for part in (customer.first_name or "", customer.last_name or "")
            if part.strip()
        )
        address_snapshot = {}
        if order.adresse is not None:
            address_snapshot = {
                "street": order.adresse.rue or "",
                "postal_code": order.adresse.code_postal or "",
                "city": order.adresse.ville or "",
                "country": order.adresse.pays or "",
            }

        items_snapshot = []
        lines = order.lignes.using(database).order_by("pk").iterator(
            chunk_size=BATCH_SIZE
        )
        for line in lines:
            quantity = int(line.quantite)
            unit_price = Decimal(line.prix_unitaire)
            items_snapshot.append(
                {
                    "name": line.nom_produit_snapshot or "Produit indisponible",
                    "quantity": quantity,
                    "unit_price": decimal_snapshot(unit_price),
                    "subtotal": decimal_snapshot(unit_price * quantity),
                }
            )

        batch.append(
            OrderReceipt(
                commande_id=order.pk,
                public_id=uuid.uuid4(),
                issued_at=order.date_commande,
                language_code=normalize_language(order.language_code),
                currency=(order.currency or "EUR").upper(),
                total=order.total,
                payment_channel=order.payment_channel or "",
                issuer_name=settings.ORDER_RECEIPT_ISSUER_NAME,
                issuer_contact=settings.ORDER_RECEIPT_ISSUER_CONTACT,
                customer_name=customer_name,
                customer_email=customer.email,
                address_snapshot=address_snapshot,
                items_snapshot=items_snapshot,
            )
        )
        if len(batch) == BATCH_SIZE:
            OrderReceipt.objects.using(database).bulk_create(batch)
            batch = []

    if batch:
        OrderReceipt.objects.using(database).bulk_create(batch)


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0018_order_line_snapshots"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrderReceipt",
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
                    "public_id",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("issued_at", models.DateTimeField(editable=False)),
                ("language_code", models.CharField(editable=False, max_length=10)),
                ("currency", models.CharField(editable=False, max_length=10)),
                (
                    "total",
                    models.DecimalField(
                        decimal_places=2,
                        editable=False,
                        max_digits=10,
                    ),
                ),
                (
                    "payment_channel",
                    models.CharField(blank=True, editable=False, max_length=20),
                ),
                ("issuer_name", models.CharField(editable=False, max_length=255)),
                (
                    "issuer_contact",
                    models.CharField(blank=True, editable=False, max_length=255),
                ),
                (
                    "customer_name",
                    models.CharField(blank=True, editable=False, max_length=301),
                ),
                ("customer_email", models.EmailField(editable=False, max_length=254)),
                (
                    "address_snapshot",
                    models.JSONField(default=dict, editable=False),
                ),
                (
                    "items_snapshot",
                    models.JSONField(default=list, editable=False),
                ),
                (
                    "commande",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="receipt",
                        to="shop.commande",
                    ),
                ),
            ],
        ),
        migrations.RunPython(
            backfill_paid_order_receipts,
            migrations.RunPython.noop,
        ),
    ]
