import io
import base64
import matplotlib.pyplot as plt
from django.utils.html import format_html
from django.contrib import admin
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from .models import (
    Partenaire, Publicite, Abonnement, AbonnementUtilisateur,
    Don, LienAffiliation, Revenu
)

@admin.register(Partenaire)
class PartenaireAdmin(admin.ModelAdmin):
    list_display = ("nom", "site_web")
    search_fields = ("nom",)


@admin.register(Publicite)
class PubliciteAdmin(admin.ModelAdmin):
    list_display = ("titre", "partenaire", "date_debut", "date_fin", "actif")
    list_filter = ("actif", "date_debut", "date_fin")
    search_fields = ("titre", "partenaire__nom")


@admin.register(Abonnement)
class AbonnementAdmin(admin.ModelAdmin):
    list_display = ("nom", "prix", "duree_jours")
    prepopulated_fields = {"slug": ("nom",)}


@admin.register(AbonnementUtilisateur)
class AbonnementUtilisateurAdmin(admin.ModelAdmin):
    list_display = ("utilisateur", "abonnement", "date_debut", "date_fin", "actif")
    list_filter = ("actif", "abonnement")
    search_fields = ("utilisateur__username", "utilisateur__email")


@admin.register(Don)
class DonAdmin(admin.ModelAdmin):
    list_display = ("utilisateur", "montant", "date")
    list_filter = ("date",)
    search_fields = ("utilisateur__username",)


from django.contrib import admin
from django.utils.html import format_html
from .models import LienAffiliation


@admin.register(LienAffiliation)
class LienAffiliationAdmin(admin.ModelAdmin):
    list_display = ("article", "plateforme", "revenu_genere", "commission_coloree")

    def commission_coloree(self, obj):
        commission = obj.revenu_genere * 0.10  # ex: 10% du revenu
        couleur = "green" if commission >= 50 else "orange" if commission >= 20 else "red"
        return format_html(
            '<span style="color:{}; font-weight:bold;">{:.2f} €</span>',
            couleur,
            commission
        )

    commission_coloree.short_description = "Commission estimée"






# --- Tes autres admins déjà définis ci-dessus --- #

@admin.register(Revenu)
class RevenuAdmin(admin.ModelAdmin):
    list_display = ("type", "montant", "date")
    list_filter = ("type", "date")
    change_list_template = "admin/revenu_change_list.html"

    def changelist_view(self, request, extra_context=None):
        # --- Données agrégées ---
        qs = self.get_queryset(request)
        data = (
            qs.annotate(month=TruncMonth("date"))
              .values("month", "type")
              .annotate(total=Sum("montant"))
              .order_by("month")
        )

        # --- Transformer en dict {mois: {type: montant}} ---
        monthly_data = {}
        for entry in data:
            month = entry["month"].strftime("%Y-%m") if entry["month"] else "N/A"
            if month not in monthly_data:
                monthly_data[month] = {}
            monthly_data[month][entry["type"]] = float(entry["total"])

        # --- Générer le graphique ---
        fig, ax = plt.subplots(figsize=(8, 4))
        months = list(monthly_data.keys())
        types = ["DON", "SUB", "PUB", "AFF"]

        for t in types:
            values = [monthly_data[m].get(t, 0) for m in months]
            ax.plot(months, values, marker="o", label=t)

        ax.set_title("Revenus mensuels par type")
        ax.set_xlabel("Mois")
        ax.set_ylabel("Montant (€)")
        ax.legend()

        # Convertir le graphique en base64
        buffer = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buffer, format="png")
        buffer.seek(0)
        image_png = buffer.getvalue()
        buffer.close()
        graphic = base64.b64encode(image_png).decode("utf-8")

        extra_context = extra_context or {}
        extra_context["chart"] = graphic
        return super().changelist_view(request, extra_context=extra_context)

from django.contrib.admin import AdminSite
from django.utils.timezone import now
from django.db.models import Sum
from .models import Revenu


class CustomAdminSite(AdminSite):
    site_header = "Administration du Blog & Shop"
    site_title = "Tableau de bord"
    index_title = "Bienvenue sur le tableau de bord"

    def each_context(self, request):
        context = super().each_context(request)

        # Calcul des revenus du mois en cours
        today = now().date()
        mois_courant = today.month
        annee_courante = today.year

        total_revenus = (
            Revenu.objects.filter(date__year=annee_courante, date__month=mois_courant)
            .aggregate(Sum("montant"))["montant__sum"]
            or 0
        )

        context["revenus_mois"] = total_revenus
        return context


# Remplacer l’admin par défaut par le nôtre
custom_admin_site = CustomAdminSite(name="custom_admin")
