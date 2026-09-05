from django.db import migrations, models


def populate_french_article_translations(apps, schema_editor):
    database = schema_editor.connection.alias
    Article = apps.get_model("articles", "Article")

    Article.objects.using(database).filter(
        models.Q(titre_fr__isnull=True) | models.Q(titre_fr="")
    ).update(titre_fr=models.F("titre"))

    Article.objects.using(database).filter(
        models.Q(contenu_fr__isnull=True) | models.Q(contenu_fr="")
    ).update(contenu_fr=models.F("contenu"))


class Migration(migrations.Migration):
    dependencies = [
        ("articles", "0005_article_translations"),
    ]

    operations = [
        # The legacy columns remain untouched, so an exact reverse copy is unnecessary.
        migrations.RunPython(
            populate_french_article_translations,
            migrations.RunPython.noop,
        ),
    ]
