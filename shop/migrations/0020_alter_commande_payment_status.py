from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0019_order_receipts"),
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
                    ("REFUNDED", "Remboursée"),
                    ("FAILED", "Échouée"),
                    ("CANCELED", "Annulée"),
                ],
                default="PENDING",
                max_length=20,
            ),
        ),
    ]
