from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0007_commande_checkout_and_cart_tracking"),
    ]

    operations = [
        migrations.AlterField(
            model_name="commande",
            name="payment_channel",
            field=models.CharField(
                blank=True,
                choices=[
                    ("CARD", "Carte bancaire"),
                    ("MOBILE_MONEY", "Mobile Money"),
                    ("STRIPE", "Stripe"),
                    ("CINETPAY", "CinetPay"),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="commande",
            name="payment_status",
            field=models.CharField(
                choices=[
                    ("PENDING", "En attente"),
                    ("PROCESSING", "Paiement en cours"),
                    ("SUCCESS", "Payée"),
                    ("FAILED", "Échouée"),
                ],
                default="PENDING",
                max_length=20,
            ),
        ),
    ]
