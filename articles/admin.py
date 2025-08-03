from django.contrib import admin
from .models import Article

@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ('titre', 'slug', 'date_publication')
    prepopulated_fields = {"slug": ("titre",)}
    search_fields = ('titre', 'contenu')
    list_filter = ('date_publication',)
