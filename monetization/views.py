from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from .models import Revenu, AbonnementUtilisateur, Don
from django.db.models import Sum

def est_admin(user):
    return user.is_superuser


from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, redirect
from django.contrib import messages

@staff_member_required(login_url='home')  # redirige si pas admin
def dashboard_view(request):
    # 🔹 Statistiques simples
    stats = {
        "revenus_publicite": 120.50,
        "revenus_affiliation": 89.30,
        "abonnements_premium": 45,
    }

    # 🔹 Revenus mensuels pour graphiques
    revenus_mensuels = {
        "labels": ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin"],
        "publicite": [50, 80, 120, 150, 200, 250],
        "affiliation": [30, 40, 60, 80, 90, 100],
        "premium": [10, 20, 30, 35, 40, 45],
    }

    # 🔹 Totaux pour KPI et camembert
    totaux = {
        "total_publicite": sum(revenus_mensuels["publicite"]),
        "total_affiliation": sum(revenus_mensuels["affiliation"]),
        "total_premium": sum(revenus_mensuels["premium"]),
    }

    return render(request, "monetization/dashboard.html", {
        "stats": stats,
        "revenus_mensuels": revenus_mensuels,
        "totaux": totaux,
    })



from django.shortcuts import render, redirect
from django.contrib import messages
from .forms import PartenariatForm, AffiliationForm

def partenariat_view(request):
    if request.method == "POST":
        form = PartenariatForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Votre demande de partenariat a été envoyée avec succès !")
            return redirect("monetization:partenariat")
    else:
        form = PartenariatForm()
    return render(request, "monetization/partenariat.html", {"form": form})


def affiliation_view(request):
    if request.method == "POST":
        form = AffiliationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Votre demande d’affiliation a été envoyée avec succès !")
            return redirect("monetization:affiliation")
    else:
        form = AffiliationForm()
    return render(request, "monetization/affiliation.html", {"form": form})

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta

from .models import Abonnement, AbonnementUtilisateur

def abonnements_view(request):
    abonnements = Abonnement.objects.all()
    return render(request, "monetization/abonnements.html", {"abonnements": abonnements})


def souscrire_abonnement(request, slug):
    abonnement = get_object_or_404(Abonnement, slug=slug)
    if request.user.is_authenticated:
        date_debut = timezone.now()
        date_fin = date_debut + timedelta(days=abonnement.duree_jours)

        AbonnementUtilisateur.objects.create(
            utilisateur=request.user,
            abonnement=abonnement,
            date_fin=date_fin,
            actif=True
        )
        messages.success(request, f"Vous avez souscrit à l’abonnement {abonnement.nom} !")
        return redirect("monetization:abonnements")
    else:
        messages.error(request, "Vous devez être connecté pour souscrire.")
        return redirect("login")

from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Don

def don_view(request):
    if request.method == "POST":
        montant = request.POST.get("montant")
        if montant and request.user.is_authenticated:
            Don.objects.create(utilisateur=request.user, montant=montant)
            messages.success(request, f"Merci pour votre don de {montant} € ❤️")
            return redirect("monetization:don")
        else:
            messages.error(request, "Veuillez vous connecter et saisir un montant valide.")
    return render(request, "monetization/don.html")

def paiement_view(request):
    return render(request, "monetization/paiement.html")
