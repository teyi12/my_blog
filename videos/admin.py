from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from modeltranslation.admin import TranslationAdmin

from .models import Video


@admin.register(Video)
class VideoAdmin(TranslationAdmin):
    list_display = (
        "titre",
        "categorie",
        "auteur",
        "est_publie",
        "is_premium",
        "en_vedette",
        "date_publication",
    )
    list_editable = ("est_publie", "en_vedette")
    list_filter = (
        "categorie",
        "est_publie",
        "is_premium",
        "en_vedette",
        "date_publication",
    )
    search_fields = ("titre_fr", "titre_de", "titre_en", "auteur__email")
    prepopulated_fields = {"slug": ("titre_fr",)}
    autocomplete_fields = ("categorie",)
    readonly_fields = ("date_publication",)
    fieldsets = (
        (
            _("Contenu"),
            {"fields": ("titre", "description", "categorie")},
        ),
        (
            _("Média YouTube"),
            {"fields": ("youtube_url", "miniature", "miniature_alt")},
        ),
        (
            _("Publication"),
            {"fields": ("slug", "auteur", "date_publication", "est_publie")},
        ),
        (
            _("Visibilité"),
            {"fields": ("is_premium", "en_vedette", "ordre_affichage")},
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ("slug",)
        return self.readonly_fields

    def get_prepopulated_fields(self, request, obj=None):
        if obj:
            return {}
        return super().get_prepopulated_fields(request, obj)

    def save_model(self, request, obj, form, change):
        if not obj.auteur_id:
            obj.auteur = request.user
        super().save_model(request, obj, form, change)

# Register your models here.
