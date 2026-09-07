from django.contrib import admin
from modeltranslation.admin import TranslationAdmin

from .models import Article, ArticleMedia, CategorieArticle


@admin.register(CategorieArticle)
class CategorieArticleAdmin(TranslationAdmin):
    list_display = ("nom", "slug", "date_creation")
    prepopulated_fields = {"slug": ("nom_fr",)}
    search_fields = ("nom_fr", "nom_de", "nom_en")

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ("slug",)
        return ()

    def get_prepopulated_fields(self, request, obj=None):
        if obj:
            return {}
        return super().get_prepopulated_fields(request, obj)


class ArticleMediaInline(admin.TabularInline):
    model = ArticleMedia
    extra = 1


@admin.register(Article)
class ArticleAdmin(TranslationAdmin):
    list_display = (
        "titre",
        "categorie",
        "en_vedette",
        "ordre_affichage",
        "is_premium",
        "date_publication",
        "auteur",
    )
    list_editable = ("en_vedette", "ordre_affichage")
    prepopulated_fields = {"slug": ("titre_fr",)}
    search_fields = (
        "titre_fr",
        "titre_de",
        "titre_en",
        "contenu_fr",
        "contenu_de",
        "contenu_en",
        "auteur__email",
    )
    list_filter = (
        "categorie",
        "en_vedette",
        "is_premium",
        "est_sponsorise",
        "date_publication",
    )
    autocomplete_fields = ("categorie",)
    inlines = [ArticleMediaInline]

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ("slug",)
        return ()

    def get_prepopulated_fields(self, request, obj=None):
        if obj:
            return {}
        return super().get_prepopulated_fields(request, obj)


@admin.register(ArticleMedia)
class ArticleMediaAdmin(admin.ModelAdmin):
    list_display = ("article", "type", "fichier", "date_ajout")
    list_filter = ("type", "date_ajout")
