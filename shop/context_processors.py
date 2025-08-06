# shop/context_processors.py

from .models import Produit, Categorie


def nav_context(request):
    panier = request.session.get("panier", {})
    panier_items_count = sum(panier.values())

    return {
        "categories_nav": Categorie.objects.all(),
        "produits_nav": Produit.objects.all(),
        "panier_items_count": panier_items_count,
    }
