from django.contrib import admin
from modeltranslation.admin import TranslationAdmin

from .models import Article, ArticleMedia


class ArticleMediaInline(admin.TabularInline):
    model = ArticleMedia
    extra = 1


@admin.register(Article)
class ArticleAdmin(TranslationAdmin):
    list_display = ("titre", "auteur", "date_publication", "est_sponsorise", "is_premium")
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
    list_filter = ("est_sponsorise", "is_premium", "date_publication")
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
