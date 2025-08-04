from django.shortcuts import render, get_object_or_404, redirect
from .models import Produit, Commande, LigneCommande
from .forms import ProduitForm, AjouterAuPanierForm
from decimal import Decimal
from django.contrib.auth.decorators import login_required

def liste_produits(request):
    produits = Produit.objects.all()
    return render(request, 'shop/liste.html', {'produits': produits})

def detail_produit(request, slug):
    produit = get_object_or_404(Produit, slug=slug)
    form = AjouterAuPanierForm()
    return render(request, 'shop/detail.html', {'produit': produit, 'form': form})

@login_required
def creer_produit(request):
    form = ProduitForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        form.save()
        return redirect('shop:liste')
    return render(request, 'shop/creer.html', {'form': form})

def ajouter_au_panier(request, slug):
    produit = get_object_or_404(Produit, slug=slug)
    form = AjouterAuPanierForm(request.POST)
    if form.is_valid():
        panier = request.session.get('panier', {})
        quantite = int(form.cleaned_data['quantite'])
        panier[str(produit.id)] = panier.get(str(produit.id), 0) + quantite
        request.session['panier'] = panier
    return redirect('shop:panier')

from django.urls import reverse

from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from .models import Produit

def afficher_panier(request):
    panier = request.session.get('panier', {})
    panier_detail = {}
    total = Decimal('0')

    for produit_id, quantite in panier.items():
        produit = get_object_or_404(Produit, pk=produit_id)
        sous_total = produit.prix * quantite
        panier_detail[produit_id] = {
            'nom': produit.nom,
            'prix': produit.prix,
            'quantite': quantite,
            'sous_total': sous_total,
        }
        total += sous_total

    # Gestion des actions POST (modifier/supprimer)
    if request.method == 'POST':
        action = request.POST.get('action')
        produit_id = request.POST.get('article_id')

        if produit_id and produit_id in panier:
            if action == 'modifier':
                nouvelle_quantite = int(request.POST.get('quantité', 1))
                if nouvelle_quantite > 0:
                    panier[produit_id] = nouvelle_quantite
                else:
                    panier.pop(produit_id)
            elif action == 'supprimer':
                panier.pop(produit_id)

            request.session['panier'] = panier
            return redirect('shop:panier')

    context = {
        'panier': panier_detail,
        'total': total,
    }
    return render(request, 'shop/panier.html', context)


@login_required
def passer_commande(request):
    panier = request.session.get("panier", {})
    if not panier:
        return redirect("shop:panier")

    commande = Commande.objects.create(client=request.user)
    total = Decimal('0')

    for produit_id, quantite in panier.items():
        produit = get_object_or_404(Produit, pk=produit_id)
        ligne = LigneCommande.objects.create(
            commande=commande,
            produit=produit,
            quantite=quantite,
            prix_unitaire=produit.prix
        )
        total += ligne.sous_total()

    commande.total = total
    commande.save()
    request.session['panier'] = {}

    return render(request, "shop/confirmation.html", {"commande": commande})

# shop/views.py

# shop/views.py

from django.shortcuts import get_object_or_404, render
from .models import Categorie, Produit

def produits_par_categorie(request, slug):
    categorie = get_object_or_404(Categorie, slug=slug)
    produits = Produit.objects.filter(categorie=categorie)
    return render(request, 'shop/produits_par_categorie.html', {
        'categorie': categorie,
        'produits': produits,
    })

