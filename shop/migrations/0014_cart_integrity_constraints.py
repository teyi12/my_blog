from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0013_normalize_cart_data"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="cart",
            constraint=models.UniqueConstraint(
                fields=("user",),
                condition=models.Q(actif=True, user__isnull=False),
                name="one_active_cart_per_user",
            ),
        ),
        migrations.AddConstraint(
            model_name="cartitem",
            constraint=models.UniqueConstraint(
                fields=("cart", "produit"),
                name="unique_product_per_cart",
            ),
        ),
    ]
