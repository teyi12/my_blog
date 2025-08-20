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

def afficher_panier(request):
    panier = request.session.get("panier", {})
    panier_detail = {}
    total = Decimal("0")

    for slug, item in panier.items():
        try:
            produit = Produit.objects.get(slug=slug)
        except Produit.DoesNotExist:
            continue  # produit supprimé de la BDD

        quantite = int(item.get("quantite", 1))
        prix = Decimal(item["prix"])
        sous_total = prix * quantite

        panier_detail[slug] = {
            "nom": produit.nom,
            "slug": produit.slug,
            "prix": prix,
            "quantite": quantite,
            "sous_total": sous_total,
            "image": item.get("image"),
        }
        total += sous_total

    if request.method == "POST":
        action = request.POST.get("action")
        slug_post = request.POST.get("article_id")

        if slug_post and slug_post in panier:
            if action == "modifier":
                nouvelle_quantite = int(request.POST.get("quantite", 1))
                if nouvelle_quantite > 0:
                    panier[slug_post]["quantite"] = nouvelle_quantite
                else:
                    panier.pop(slug_post)
            elif action == "supprimer":
                panier.pop(slug_post)

            request.session["panier"] = panier
            return redirect("shop:panier")

    context = {
        "panier": panier_detail,
        "total": total,
    }
    return render(request, "shop/panier.html", context)


# shop/views.py
# shop/views.py
from django.shortcuts import get_object_or_404, redirect
from .models import Produit
from .forms import AjouterAuPanierForm

# shop/views.py
from django.shortcuts import get_object_or_404, redirect
from .models import Produit
from .forms import AjouterAuPanierForm

def ajouter_au_panier(request, slug):
    produit = get_object_or_404(Produit, slug=slug)
    panier = request.session.get("panier", {})

    # Si c'est un POST avec un formulaire, on prend la quantité soumise
    if request.method == "POST":
        form = AjouterAuPanierForm(request.POST)
        if form.is_valid():
            quantite = int(form.cleaned_data.get("quantite", 1))
        else:
            quantite = 1
    else:
        # Si c'est un GET (ex: bouton "Ajouter au panier" depuis la liste)
        quantite = 1

    # Si le produit est déjà dans le panier, on ajoute la quantité
    if slug in panier:
        panier[slug]["quantite"] += quantite
    else:
        panier[slug] = {
            "nom": produit.nom,
            "slug": produit.slug,
            "prix": str(produit.prix),  # ⚠️ Decimal doit être casté en str pour la session
            "quantite": quantite,
            "image": produit.image.url if produit.image else None,
        }

    request.session["panier"] = panier  # sauvegarde en session

    return redirect("shop:panier")

@login_required
def passer_commande(request):
    panier = request.session.get("panier", {})
    if not panier:
        return redirect("shop:panier")

    commande = Commande.objects.create(client=request.user)
    total = Decimal("0")

    for produit_id, item in panier.items():
        produit = get_object_or_404(Produit, pk=produit_id)

        quantite = int(request.POST.get("quantité", 1))
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

