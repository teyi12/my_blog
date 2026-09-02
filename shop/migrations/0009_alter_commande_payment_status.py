from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0008_order_payment_processing_state"),
    ]

    operations = [
        migrations.AlterField(
            model_name="commande",
            name="payment_status",
            field=models.CharField(
                choices=[
                    ("PENDING", "En attente"),
                    ("PROCESSING", "Paiement en cours"),
                    ("SUCCESS", "Payée"),
                    ("FAILED", "Échouée"),
                    ("CANCELED", "Annulée"),
                ],
                default="PENDING",
                max_length=20,
            ),
        ),
    ]
