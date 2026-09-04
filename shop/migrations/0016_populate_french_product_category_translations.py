from django.db import migrations, models


def populate_french_translations(apps, schema_editor):
    database = schema_editor.connection.alias
    Categorie = apps.get_model("shop", "Categorie")
    Produit = apps.get_model("shop", "Produit")

    Categorie.objects.using(database).filter(
        models.Q(nom_fr__isnull=True) | models.Q(nom_fr="")
    ).update(nom_fr=models.F("nom"))

    Produit.objects.using(database).filter(
        models.Q(nom_fr__isnull=True) | models.Q(nom_fr="")
    ).update(nom_fr=models.F("nom"))

    Produit.objects.using(database).filter(
        models.Q(description_fr__isnull=True) | models.Q(description_fr="")
    ).update(description_fr=models.F("description"))


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0015_product_category_translations"),
    ]

    operations = [
        migrations.RunPython(populate_french_translations, migrations.RunPython.noop),
    ]
