import uuid

from django.db import migrations, models
from django.db.models import Q


def populate_idempotency_keys(apps, schema_editor):
    Payment = apps.get_model("payments", "Payment")
    for payment in Payment.objects.filter(idempotency_key__isnull=True).iterator():
        payment.idempotency_key = uuid.uuid4()
        payment.save(update_fields=["idempotency_key"])


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0003_adresse_type_adresse_alter_adresse_utilisateur"),
        ("shop", "0008_order_payment_processing_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="checkout_url",
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="payment",
            name="idempotency_key",
            field=models.UUIDField(editable=False, null=True, unique=True),
        ),
        migrations.RunPython(
            populate_idempotency_keys,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="payment",
            name="idempotency_key",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name="payment",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "En attente"),
                    ("PROCESSING", "En cours"),
                    ("SUCCESS", "Réussi"),
                    ("FAILED", "Échoué"),
                    ("CANCELED", "Annulé"),
                ],
                default="PENDING",
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.UniqueConstraint(
                fields=("commande",),
                condition=Q(status="PROCESSING"),
                name="one_processing_payment_per_order",
            ),
        ),
    ]
