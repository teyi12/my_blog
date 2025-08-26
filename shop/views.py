from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .models import Produit, Cart, CartItem
import json


@login_required
def panier_view(request):
    cart, created = Cart.objects.get_or_create(user=request.user)
    return render(request, "shop/panier.html", {"cart": cart})


@login_required
def update_panier(request):
    if request.method == "POST":
        data = json.loads(request.body.decode("utf-8"))
        action = data.get("action")
        item_id = data.get("item_id")
        quantite = int(data.get("quantite", 1))

        cart, _ = Cart.objects.get_or_create(user=request.user)

        if action == "modifier" and item_id:
            item = get_object_or_404(CartItem, id=item_id, cart=cart)
            item.quantite = max(1, quantite)
            item.save()
            return JsonResponse({
                "success": True,
                "total": float(cart.total()),
                "sous_total": float(item.sous_total()),
                "total_articles": cart.total_articles()
            })

        elif action == "supprimer" and item_id:
            item = get_object_or_404(CartItem, id=item_id, cart=cart)
            item.delete()
            return JsonResponse({
                "success": True,
                "total": float(cart.total()),
                "sous_total": 0,
                "total_articles": cart.total_articles()
            })

    return JsonResponse({"success": False}, status=400)


@login_required
def ajouter_panier(request, slug):
    produit = get_object_or_404(Produit, slug=slug)
    cart, created = Cart.objects.get_or_create(user=request.user)

    item, created = CartItem.objects.get_or_create(cart=cart, produit=produit)
    if not created:
        item.quantite += 1
        item.save()

    return redirect("shop:panier")


from django.views.generic import ListView, DetailView


class ProduitListView(ListView):
    model = Produit
    template_name = "shop/liste.html"
    context_object_name = "produits"
    paginate_by = 12  # pagination (12 produits par page)


class ProduitDetailView(DetailView):
    model = Produit
    template_name = "shop/detail.html"
    context_object_name = "produit"
    slug_field = "slug"
    slug_url_kwarg = "slug"


def produits_par_categorie(request, slug):
    categorie = get_object_or_404(Categorie, slug=slug)
    produits = Produit.objects.filter(categorie=categorie)
    return render(
        request, "shop/liste.html", {"produits": produits, "categorie": categorie}
    )
