import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0006_alter_lignecommande_prix_unitaire_cart_cartitem"),
    ]

    operations = [
        migrations.AddField(
            model_name="commande",
            name="cart_finalized_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="commande",
            name="checkout_token",
            field=models.UUIDField(blank=True, editable=False, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="commande",
            name="source_cart",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="commandes",
                to="shop.cart",
            ),
        ),
        migrations.AddField(
            model_name="lignecommande",
            name="source_cart_item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="lignes_commande",
                to="shop.cartitem",
            ),
        ),
    ]
