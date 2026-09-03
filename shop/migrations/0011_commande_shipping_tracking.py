from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0010_commande_fulfillment_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="commande",
            name="carrier",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="commande",
            name="tracking_number",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="commande",
            name="shipped_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="commande",
            name="delivered_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]
