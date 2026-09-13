from django.contrib import admin
from django.db.models import F, Q
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from modeltranslation.admin import TranslationAdmin

from .models import Categorie, Produit, Commande, LigneCommande, StockMovement


class StockAlertFilter(admin.SimpleListFilter):
    title = _("Alerte de stock")
    parameter_name = "stock_alert"

    def lookups(self, request, model_admin):
        return (("low", _("Épuisé ou stock faible")),)

    def queryset(self, request, queryset):
        if self.value() == "low":
            return (
                queryset.filter(stock__isnull=False)
                .filter(Q(fichier="") | Q(fichier__isnull=True))
                .filter(
                    Q(stock=0)
                    | Q(
                        low_stock_threshold__isnull=False,
                        stock__lte=F("low_stock_threshold"),
                    )
                )
            )
        return queryset


@admin.register(Categorie)
class CategorieAdmin(TranslationAdmin):
    list_display = ("nom", "slug")
    prepopulated_fields = {"slug": ("nom_fr",)}
    search_fields = ("nom_fr", "nom_de", "nom_en")


@admin.register(Produit)
class ProduitAdmin(TranslationAdmin):
    list_display = (
        "nom",
        "categorie",
        "prix",
        "stock",
        "low_stock_threshold",
        "stock_alert",
        "en_vedette",
    )
    list_filter = (StockAlertFilter, "categorie", "en_vedette")
    search_fields = (
        "nom_fr",
        "nom_de",
        "nom_en",
        "description_fr",
        "description_de",
        "description_en",
    )
    prepopulated_fields = {"slug": ("nom_fr",)}
    autocomplete_fields = ("categorie",)
    readonly_fields = ("stock", "stock_adjustment")

    @admin.display(boolean=True, description=_("Stock faible"))
    def stock_alert(self, obj):
        return (
            obj.stock_est_gere
            and (
                obj.stock == 0
                or (
                    obj.low_stock_threshold is not None
                    and obj.stock <= obj.low_stock_threshold
                )
            )
        )

    @admin.display(description=_("Ajustement de stock"))
    def stock_adjustment(self, obj):
        if obj is None or obj.pk is None:
            return "—"
        return format_html(
            '<a href="{}?produit={}">{}</a>',
            reverse("shop:inventory_gestion"),
            obj.pk,
            _("Ajuster le stock"),
        )


class LigneCommandeInline(admin.TabularInline):
    model = LigneCommande
    extra = 1
    fields = (
        "nom_produit_affiche",
        "produit",
        "quantite",
        "prix_unitaire",
        "stock_reserved_quantity",
        "sous_total",
    )
    readonly_fields = (
        "nom_produit_affiche",
        "stock_reserved_quantity",
        "sous_total",
    )


@admin.register(Commande)
class CommandeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "client",
        "date_commande",
        "total",
        "payment_status",
        "fulfillment_status",
        "carrier",
        "payment_channel",
        "currency",
    )
    list_filter = (
        "payment_status",
        "fulfillment_status",
        "payment_channel",
        "currency",
        "date_commande",
    )
    search_fields = (
        "client__email",
        "client__first_name",
        "client__last_name",
        "transaction_id",
        "carrier",
        "tracking_number",
    )
    readonly_fields = (
        "total",
        "date_commande",
        "payment_status",
        "payment_channel",
        "transaction_id",
        "fulfillment_status",
        "carrier",
        "tracking_number",
        "shipped_at",
        "delivered_at",
        "inventory_status",
        "inventory_cycle",
        "stock_reservation_expires_at",
    )
    inlines = [LigneCommandeInline]


@admin.register(LigneCommande)
class LigneCommandeAdmin(admin.ModelAdmin):
    list_display = (
        "commande",
        "nom_produit_affiche",
        "quantite",
        "prix_unitaire",
        "stock_reserved_quantity",
        "sous_total",
    )
    autocomplete_fields = ("commande", "produit")
    readonly_fields = ("nom_produit_affiche", "stock_reserved_quantity")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "produit",
        "movement_type",
        "quantity",
        "stock_before",
        "stock_after",
        "commande",
        "actor",
    )
    list_filter = ("movement_type", "created_at")
    search_fields = (
        "produit__nom",
        "product_name_snapshot",
        "reason",
        "idempotency_key",
    )
    readonly_fields = tuple(
        field.name for field in StockMovement._meta.concrete_fields
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
