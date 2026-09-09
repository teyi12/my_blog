from django.contrib import admin
from .models import Adresse, DonationPaymentAttempt, Payment
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


@admin.register(DonationPaymentAttempt)
class DonationPaymentAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "utilisateur",
        "montant",
        "devise",
        "status",
        "stripe_session_id",
        "created_at",
        "updated_at",
    )
    list_filter = ("status", "created_at", "updated_at")
    search_fields = ("utilisateur__email", "stripe_session_id")
    ordering = ("-created_at",)
    actions = None
    fields = (
        "id",
        "utilisateur",
        "montant",
        "devise",
        "status",
        "stripe_session_id",
        "idempotency_key",
        "checkout_url",
        "don",
        "raw_response",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

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


from django.contrib import admin
from .models import Adresse


@admin.register(Adresse)
class AdresseAdmin(admin.ModelAdmin):
    list_display = (
        "utilisateur",
        "type_adresse",
        "rue",
        "ville",
        "code_postal",
        "pays",
        "telephone",
        "cree_le",
    )
    list_filter = ("type_adresse", "pays", "ville", "cree_le")
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
