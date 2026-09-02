from django.db import migrations, models


def reconcile_historical_pending_payments(apps, schema_editor):
    """PENDING predates provider verification; retain it as terminal history."""
    Payment = apps.get_model("payments", "Payment")
    Payment.objects.filter(status="PENDING").update(status="CANCELED")


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0004_payment_idempotency"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="initialization_started_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="initialization_token",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(
            reconcile_historical_pending_payments,
            migrations.RunPython.noop,
        ),
    ]
