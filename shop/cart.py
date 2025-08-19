from decimal import Decimal
from django.shortcuts import get_object_or_404
from shop.models import Produit

def get_cart(session):
    """Récupère le panier et normalise la structure"""
    panier = session.get("panier", {})

    # Normalisation : forcer la structure {"quantite": x}
    for produit_id, item in list(panier.items()):
        if isinstance(item, int):  # ancien format
            panier[produit_id] = {"quantite": item}
        elif isinstance(item, dict) and "quantite" not in item:
            # S’il y a un dict mais sans la clé quantite
            panier[produit_id]["quantite"] = 1

    session["panier"] = panier
    session.modified = True
    return panier


def save_cart(session, panier):
    """Sauvegarde le panier dans la session"""
    session["panier"] = panier
    session.modified = True

def add_to_cart(session, produit_id, quantite=1):
    """Ajoute ou met à jour un produit dans le panier"""
    panier = get_cart(session)
    produit_id = str(produit_id)
    if produit_id in panier:
        panier[produit_id]["quantite"] += quantite
    else:
        panier[produit_id] = {"quantite": quantite}
    save_cart(session, panier)

def remove_from_cart(session, produit_id):
    """Supprime un produit du panier"""
    panier = get_cart(session)
    produit_id = str(produit_id)
    if produit_id in panier:
        del panier[produit_id]
        save_cart(session, panier)

def update_quantity(session, produit_id, quantite):
    """Met à jour la quantité d’un produit"""
    panier = get_cart(session)
    produit_id = str(produit_id)
    if produit_id in panier:
        if quantite > 0:
            panier[produit_id]["quantite"] = quantite
        else:
            del panier[produit_id]
        save_cart(session, panier)

def get_cart_details(session):
    """Retourne le détail du panier (produits + total)"""
    panier = get_cart(session)
    panier_detail = {}
    total = Decimal("0")

    for produit_id, item in panier.items():
        produit = get_object_or_404(Produit, pk=produit_id)
        quantite = item["quantite"]
        sous_total = produit.prix * quantite
        panier_detail[produit_id] = {
            "nom": produit.nom,
            "prix": produit.prix,
            "quantite": quantite,
            "sous_total": sous_total,
        }
        total += sous_total

    return panier_detail, total
