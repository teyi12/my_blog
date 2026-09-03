from decimal import Decimal

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from .forms import AffiliationForm, PartenariatForm
from .models import Abonnement, Publicite, Revenu


@staff_member_required(login_url="home")
def dashboard_view(request):
    """Dashboard interne basé uniquement sur les revenus réellement enregistrés."""
    totals = {
        row["type"]: row["total"] or Decimal("0")
        for row in Revenu.objects.values("type").annotate(total=Sum("montant"))
    }

    context = {
        "totaux": {
            "publicite": totals.get("PUB", Decimal("0")),
            "affiliation": totals.get("AFF", Decimal("0")),
            "premium": totals.get("SUB", Decimal("0")),
            "dons": totals.get("DON", Decimal("0")),
            "global": sum(totals.values(), Decimal("0")),
        },
        "revenus_recents": Revenu.objects.order_by("-date")[:8],
    }
    return render(request, "monetization/dashboard.html", context)


def partenariat_view(request):
    if request.method == "POST":
        form = PartenariatForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Votre demande de partenariat a été envoyée avec succès.")
            return redirect("monetization:partenariat")
    else:
        form = PartenariatForm()
    return render(request, "monetization/partenariat.html", {"form": form})


def affiliation_view(request):
    if request.method == "POST":
        form = AffiliationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Votre demande d’affiliation a été envoyée avec succès.")
            return redirect("monetization:affiliation")
    else:
        form = AffiliationForm()
    return render(request, "monetization/affiliation.html", {"form": form})


def abonnements_view(request):
    abonnements = Abonnement.objects.all().order_by("prix", "nom")
    return render(request, "monetization/abonnements.html", {"abonnements": abonnements})


@login_required
def souscrire_abonnement(request, slug):
    """Ne jamais activer un abonnement local sans confirmation de paiement."""
    abonnement = get_object_or_404(Abonnement, slug=slug)
    messages.info(
        request,
        f"L’activation sécurisée de l’abonnement {abonnement.nom} sera disponible après intégration complète du paiement récurrent.",
    )
    return redirect("monetization:abonnements")


def don_view(request):
    """La collecte du don est déléguée au checkout Stripe sécurisé de payments."""
    return render(request, "monetization/don.html")


def paiement_view(request):
    return redirect("payments:choice")


def publicite_view(request):
    publicites = (
        Publicite.objects.select_related("partenaire")
        .filter(actif=True)
        .order_by("-date_debut")
    )
    return render(request, "monetization/publicites.html", {"publicites": publicites})
