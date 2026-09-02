
# payments/utils.py
from shop.models import Cart

def get_panier(request):
    """
    Retourne le panier de l'utilisateur.
    Crée un panier vide si nécessaire.
    """
    if not request.user.is_authenticated:
        return None
    cart, _ = Cart.objects.get_or_create(user=request.user)
    return cart


def get_total(request):
    """
    Retourne le total du panier en base.
    """
    cart = get_panier(request)
    if not cart:
        return 0
    return cart.total()


def enrichir_panier(request):
    """
    Retourne un dictionnaire enrichi du panier,
    utile pour l'affichage ou l’API.
    """
    cart = get_panier(request)
    if not cart:
        return {"items": [], "total": 0, "total_articles": 0}

    items = []
    for item in cart.items.select_related("produit"):
        items.append({
            "id": item.id,
            "produit": item.produit.nom,
            "prix_unitaire": float(item.prix_unitaire),
            "quantite": item.quantite,
            "sous_total": float(item.sous_total()),
        })

    return {
        "items": items,
        "total": float(cart.total()),
        "total_articles": cart.total_articles(),
    }
