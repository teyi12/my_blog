from django.contrib import admin
from .models import Produit, Categorie


@admin.register(Produit)
class ProduitAdmin(admin.ModelAdmin):
    list_display = ("nom", "categorie", "prix", "en_vedette")
    list_filter = ("categorie", "en_vedette")
    search_fields = ("nom", "description")


@admin.register(Categorie)
class CategorieAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("nom",)}
