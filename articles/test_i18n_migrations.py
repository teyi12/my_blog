from importlib import import_module

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ArticleTranslationMigrationTests(TransactionTestCase):
    migrate_from = [("articles", "0004_articlemedia")]
    schema_target = [("articles", "0005_article_translations")]
    migrate_to = [("articles", "0006_populate_french_article_translations")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        User = old_apps.get_model("accounts", "CustomUser")
        Article = old_apps.get_model("articles", "Article")
        ArticleMedia = old_apps.get_model("articles", "ArticleMedia")

        self.author = User.objects.create(email="migration-author@example.com")
        self.article = Article.objects.create(
            titre="Titre historique exact",
            contenu="<h2>Introduction</h2><p>HTML <strong>conservé</strong>.</p>",
            slug="titre-historique-exact",
            image="articles/cloudinary-historique.jpg",
            auteur=self.author,
            sponsor="Marque inchangée",
            est_sponsorise=True,
            is_premium=True,
        )
        self.publication_date = self.article.date_publication
        self.media = ArticleMedia.objects.create(
            article=self.article,
            type="image",
            fichier="medias/cloudinary-media-historique.jpg",
        )
        self.preserved_article = Article.objects.create(
            titre="Titre source à ne pas recopier",
            contenu="<p>Contenu source à ne pas recopier</p>",
            slug="traduction-francaise-preservee",
            auteur=self.author,
        )

        executor = MigrationExecutor(connection)
        executor.migrate(self.schema_target)
        schema_apps = executor.loader.project_state(self.schema_target).apps
        schema_apps.get_model("articles", "Article").objects.filter(
            pk=self.preserved_article.pk
        ).update(
            titre_fr="Titre français déjà renseigné",
            contenu_fr="<p>Contenu français déjà renseigné</p>",
        )

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def _migrate_and_get_apps(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        return executor.loader.project_state(self.migrate_to).apps

    def test_migration_copies_exact_french_values_and_preserves_other_data(self):
        apps = self._migrate_and_get_apps()
        Article = apps.get_model("articles", "Article")
        ArticleMedia = apps.get_model("articles", "ArticleMedia")

        article = Article.objects.get(pk=self.article.pk)
        self.assertEqual(article.titre_fr, "Titre historique exact")
        self.assertEqual(
            article.contenu_fr,
            "<h2>Introduction</h2><p>HTML <strong>conservé</strong>.</p>",
        )
        self.assertIsNone(article.titre_de)
        self.assertIsNone(article.titre_en)
        self.assertIsNone(article.contenu_de)
        self.assertIsNone(article.contenu_en)
        self.assertEqual(article.slug, "titre-historique-exact")
        self.assertEqual(article.image.name, "articles/cloudinary-historique.jpg")
        self.assertEqual(article.auteur_id, self.author.pk)
        self.assertEqual(article.date_publication, self.publication_date)
        self.assertEqual(article.sponsor, "Marque inchangée")
        self.assertTrue(article.est_sponsorise)
        self.assertTrue(article.is_premium)

        media = ArticleMedia.objects.get(pk=self.media.pk)
        self.assertEqual(media.article_id, article.pk)
        self.assertEqual(media.type, "image")
        self.assertEqual(media.fichier.name, "medias/cloudinary-media-historique.jpg")

    def test_existing_french_values_are_preserved_and_migration_is_idempotent(self):
        apps = self._migrate_and_get_apps()
        Article = apps.get_model("articles", "Article")
        migration = import_module(
            "articles.migrations.0006_populate_french_article_translations"
        )

        with connection.schema_editor() as schema_editor:
            migration.populate_french_article_translations(apps, schema_editor)

        article = Article.objects.get(pk=self.preserved_article.pk)
        self.assertEqual(article.titre_fr, "Titre français déjà renseigné")
        self.assertEqual(
            article.contenu_fr,
            "<p>Contenu français déjà renseigné</p>",
        )
        self.assertIsNone(article.titre_de)
        self.assertIsNone(article.titre_en)
        self.assertIsNone(article.contenu_de)
        self.assertIsNone(article.contenu_en)
