from django.shortcuts import render, get_object_or_404, redirect
from .models import Produit, Commande, LigneCommande
from .forms import ProduitForm, AjouterAuPanierForm
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from .models import Produit, Categorie


def produits_liste(request):
    produits = Produit.objects.all().order_by("nom")
    paginator = Paginator(produits, 4)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request, "shop/liste.html", {"page_obj": page_obj}  # 👈 CORRECTION ICI
    )

def checkout(request):
    return render(request, "shop/checkout.html")

def detail_produit(request, slug):
    produit = get_object_or_404(Produit, slug=slug)
    form = AjouterAuPanierForm()
    return render(request, "shop/detail.html", {"produit": produit, "form": form})


@login_required
def creer_produit(request):
    form = ProduitForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        form.save()
        return redirect("shop:liste")
    return render(request, "shop/creer.html", {"form": form})


from django.shortcuts import get_object_or_404, redirect
from .models import Produit

def ajouter_au_panier(request, slug):
    produit = get_object_or_404(Produit, slug=slug)
    form = AjouterAuPanierForm(request.POST)
    if form.is_valid():
        panier = request.session.get("panier", {})
        quantite = int(form.cleaned_data["quantite"])

        produit_id = str(produit.id)

        # Vérifier si c'est encore l'ancien format (int)
        if produit_id in panier and isinstance(panier[produit_id], int):
            panier[produit_id] = {
                "nom": produit.nom,
                "slug": produit.slug,
                "prix": str(produit.prix),
                "quantite": panier[produit_id] + quantite,
                "image": produit.image.url if produit.image else None,
            }
        elif produit_id in panier:
            panier[produit_id]["quantite"] += quantite
        else:
            panier[produit_id] = {
                "nom": produit.nom,
                "slug": produit.slug,
                "prix": str(produit.prix),
                "quantite": quantite,
                "image": produit.image.url if produit.image else None,
            }

        request.session["panier"] = panier

    return redirect("shop:panier")




from django.urls import reverse

from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from .models import Produit


def afficher_panier(request):
    panier = request.session.get("panier", {})
    panier_detail = {}
    total = Decimal("0")

    for produit_id, item in panier.items():
        produit = get_object_or_404(Produit, pk=produit_id)

        quantite = int(item["quantite"])
        prix = Decimal(item["prix"])
        sous_total = prix * quantite

        panier_detail[produit_id] = {
            "nom": produit.nom,
            "slug": produit.slug,
            "prix": prix,
            "quantite": quantite,
            "sous_total": sous_total,
            "image": item.get("image"),
        }
        total += sous_total

    # Gestion des actions POST (modifier/supprimer)
    if request.method == "POST":
        action = request.POST.get("action")
        produit_id = request.POST.get("article_id")

        if produit_id and produit_id in panier:
            if action == "modifier":
                nouvelle_quantite = int(request.POST.get("quantité", 1))
                if nouvelle_quantite > 0:
                    panier[produit_id]["quantite"] = nouvelle_quantite
                else:
                    panier.pop(produit_id)
            elif action == "supprimer":
                panier.pop(produit_id)

            request.session["panier"] = panier
            return redirect("shop:panier")

    context = {
        "panier": panier_detail,
        "total": total,
    }
    return render(request, "shop/panier.html", context)

@login_required
def passer_commande(request):
    panier = request.session.get("panier", {})
    if not panier:
        return redirect("shop:panier")

    commande = Commande.objects.create(client=request.user)
    total = Decimal("0")

    for produit_id, item in panier.items():
        produit = get_object_or_404(Produit, pk=produit_id)

        quantite = int(item["quantite"])
        prix = Decimal(item["prix"])

        ligne = LigneCommande.objects.create(
            commande=commande,
            produit=produit,
            quantite=quantite,
            prix_unitaire=prix,
        )
        total += ligne.sous_total()

    commande.total = total
    commande.save()

    # Vider le panier après commande
    request.session["panier"] = {}

    # 🔑 On passe aussi les lignes de commande au template
    return render(request, "shop/confirmation.html", {
        "commande": commande,
        "lignes": commande.lignes.all(),
    })

# shop/views.py

from django.shortcuts import get_object_or_404, render
from .models import Categorie, Produit


def produits_par_categorie(request, slug):
    categorie = get_object_or_404(Categorie, slug=slug)
    produits = Produit.objects.filter(categorie=categorie)
    return render(
        request,
        "shop/produits_par_categorie.html",
        {
            "categorie": categorie,
            "produits": produits,
        },
    )

