from importlib import import_module

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from articles.models import Article, CategorieArticle


class VideoInitialMigrationTests(TransactionTestCase):
    migrate_from = [("videos", None)]
    migrate_to = [("videos", "0001_initial")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)

        self.category = CategorieArticle.objects.create(
            nom="Catégorie préexistante",
            slug="categorie-preexistante-video",
        )
        self.article = Article.objects.create(
            titre="Article préexistant",
            contenu="Contenu préexistant",
            slug="article-preexistant-video",
            categorie=self.category,
        )

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def test_initial_migration_is_additive_and_creates_no_content(self):
        self.assertNotIn("videos_video", connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        Video = apps.get_model("videos", "Video")
        CategorieArticle = apps.get_model("articles", "CategorieArticle")
        Article = apps.get_model("articles", "Article")

        self.assertIn("videos_video", connection.introspection.table_names())
        self.assertEqual(Video.objects.count(), 0)
        self.assertTrue(CategorieArticle.objects.filter(pk=self.category.pk).exists())
        self.assertTrue(Article.objects.filter(pk=self.article.pk).exists())

    def test_initial_migration_contains_only_the_video_model_creation(self):
        migration = import_module("videos.migrations.0001_initial").Migration

        self.assertEqual(len(migration.operations), 1)
        self.assertEqual(type(migration.operations[0]).__name__, "CreateModel")
        self.assertEqual(migration.operations[0].name, "Video")
