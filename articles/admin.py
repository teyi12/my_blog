from django.contrib import admin
from .models import Article, ArticleMedia


class ArticleMediaInline(admin.TabularInline):
    model = ArticleMedia
    extra = 1


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("titre", "auteur", "date_publication", "est_sponsorise", "is_premium")
    prepopulated_fields = {"slug": ("titre",)}
    search_fields = ("titre", "contenu", "auteur__username")
    list_filter = ("est_sponsorise", "is_premium", "date_publication")
    inlines = [ArticleMediaInline]


@admin.register(ArticleMedia)
class ArticleMediaAdmin(admin.ModelAdmin):
    list_display = ("article", "type", "fichier", "date_ajout")
    list_filter = ("type", "date_ajout")
