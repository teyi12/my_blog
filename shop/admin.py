from django.contrib import admin
from .models import Categorie, Produit, Commande, LigneCommande


@admin.register(Categorie)
class CategorieAdmin(admin.ModelAdmin):
    list_display = ("nom", "slug")
    prepopulated_fields = {"slug": ("nom",)}
    search_fields = ("nom",)


@admin.register(Produit)
class ProduitAdmin(admin.ModelAdmin):
    list_display = ("nom", "categorie", "prix", "en_vedette")
    list_filter = ("categorie", "en_vedette")
    search_fields = ("nom", "description")
    prepopulated_fields = {"slug": ("nom",)}
    autocomplete_fields = ("categorie",)


class LigneCommandeInline(admin.TabularInline):
    model = LigneCommande
    extra = 1
    fields = ("produit", "quantite", "prix_unitaire", "sous_total")
    readonly_fields = ("sous_total",)


@admin.register(Commande)
class CommandeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "client",
        "adresse",
        "date_commande",
        "total",
        "payment_status",
        "payment_channel",
        "currency",
    )
    list_filter = ("payment_status", "payment_channel", "currency", "date_commande")
    search_fields = ("client__username", "transaction_id")
    readonly_fields = ("total", "date_commande")
    inlines = [LigneCommandeInline]


@admin.register(LigneCommande)
class LigneCommandeAdmin(admin.ModelAdmin):
    list_display = ("commande", "produit", "quantite", "prix_unitaire", "sous_total")
    autocomplete_fields = ("commande", "produit")
