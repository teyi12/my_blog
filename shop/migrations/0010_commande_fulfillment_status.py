from django.db import migrations, models


def initialize_paid_orders(apps, schema_editor):
    Commande = apps.get_model("shop", "Commande")
    Commande.objects.filter(payment_status="SUCCESS").update(
        fulfillment_status="TO_PREPARE"
    )


def reverse_fulfillment_status(apps, schema_editor):
    Commande = apps.get_model("shop", "Commande")
    Commande.objects.update(fulfillment_status="WAITING_PAYMENT")


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0009_alter_commande_payment_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="commande",
            name="fulfillment_status",
            field=models.CharField(
                choices=[
                    ("WAITING_PAYMENT", "En attente de paiement"),
                    ("TO_PREPARE", "À préparer"),
                    ("PREPARING", "En préparation"),
                    ("SHIPPED", "Expédiée"),
                    ("DELIVERED", "Livrée"),
                    ("CANCELED", "Traitement annulé"),
                ],
                default="WAITING_PAYMENT",
                max_length=20,
            ),
        ),
        migrations.RunPython(initialize_paid_orders, reverse_fulfillment_status),
    ]
