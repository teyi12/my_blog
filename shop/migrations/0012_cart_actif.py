from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0011_commande_shipping_tracking"),
    ]

    operations = [
        migrations.AddField(
            model_name="cart",
            name="actif",
            field=models.BooleanField(default=True),
        ),
    ]
