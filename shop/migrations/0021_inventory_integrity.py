import django.core.validators
from django.db import migrations, models


def mark_finalized_orders_as_committed(apps, schema_editor):
    Commande = apps.get_model("shop", "Commande")
    Commande.objects.filter(
        models.Q(cart_finalized_at__isnull=False)
        | models.Q(payment_status__in=("SUCCESS", "REFUNDED"))
    ).update(inventory_status="COMMITTED")


def reset_inventory_backfill(apps, schema_editor):
    Commande = apps.get_model("shop", "Commande")
    Commande.objects.filter(inventory_status="COMMITTED").update(
        inventory_status="NONE",
        stock_reservation_expires_at=None,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0020_alter_commande_payment_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="produit",
            name="stock",
            field=models.IntegerField(
                blank=True,
                help_text=(
                    "Laissez vide pour ne pas gérer le stock. Les produits "
                    "numériques ne consomment pas de stock."
                ),
                null=True,
                validators=[django.core.validators.MinValueValidator(0)],
                verbose_name="Stock disponible",
            ),
        ),
        migrations.AddField(
            model_name="commande",
            name="inventory_status",
            field=models.CharField(
                choices=[
                    ("NONE", "Sans réservation"),
                    ("RESERVED", "Stock réservé"),
                    ("COMMITTED", "Stock consommé"),
                    ("RELEASED", "Stock libéré"),
                ],
                default="NONE",
                editable=False,
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="commande",
            name="stock_reservation_expires_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="lignecommande",
            name="stock_reserved_quantity",
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
        migrations.AddConstraint(
            model_name="produit",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(stock__isnull=True) | models.Q(stock__gte=0)
                ),
                name="product_stock_nonnegative",
            ),
        ),
        migrations.RunPython(
            mark_finalized_orders_as_committed,
            reset_inventory_backfill,
        ),
    ]
