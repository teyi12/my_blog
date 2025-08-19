from django.contrib import admin
from .models import Payment, Adresse
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DefaultUserAdmin


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "commande",
        "transaction_id",
        "channel",
        "montant",
        "devise",
        "status",
        "created_at",
    )
    list_filter = ("status", "channel", "devise", "created_at")
    search_fields = ("transaction_id", "commande__id", "commande__client__email")
    ordering = ("-created_at",)

    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Infos générales", {
            "fields": ("commande", "montant", "devise", "channel", "status")
        }),
        ("Transaction", {
            "fields": ("transaction_id", "raw_response")
        }),
        ("Dates", {
            "fields": ("created_at", "updated_at")
        }),
    )

User = get_user_model()


class AdresseInline(admin.TabularInline):  # ou StackedInline si tu veux en format bloc
    model = Adresse
    extra = 1  # nombre de formulaires vides proposés
    fields = ("rue", "ville", "code_postal", "pays", "telephone", "cree_le")
    readonly_fields = ("cree_le",)


from django.contrib import admin
from django.contrib.auth import get_user_model
from .models import Adresse

User = get_user_model()


class AdresseInline(admin.TabularInline):  # ou StackedInline si tu veux en format bloc
    model = Adresse
    extra = 1  # nombre de formulaires vides proposés
    fields = ("rue", "ville", "code_postal", "pays", "telephone", "cree_le")
    readonly_fields = ("cree_le",)


@admin.register(Adresse)
class AdresseAdmin(admin.ModelAdmin):
    list_display = (
        "utilisateur",
        "rue",
        "ville",
        "code_postal",
        "pays",
        "telephone",
        "cree_le",
    )
    list_filter = ("pays", "ville", "cree_le")
    search_fields = (
        "utilisateur__username",
        "utilisateur__email",
        "rue",
        "ville",
        "code_postal",
        "pays",
    )
    autocomplete_fields = ("utilisateur",)
    ordering = ("-cree_le",)


