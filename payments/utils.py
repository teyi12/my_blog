from decimal import Decimal

def get_panier(request):
    """
    Récupère le panier depuis la session utilisateur.
    Si le panier est vide ou inexistant, retourne un dict vide.
    """
    return request.session.get("panier", {})


def get_total(panier):
    """
    Calcule le total du panier en utilisant quantité * prix.
    Retourne un Decimal pour éviter les erreurs d'arrondi.
    """
    total = Decimal("0.00")
    for item in panier.values():
        prix = Decimal(str(item.get("prix", 0)))
        qte = int(item.get("quantité", 0))
        total += prix * qte
    return total


def get_nombre_articles(panier):
    """
    Retourne le nombre total d’articles dans le panier.
    """
    return sum(int(item.get("quantité", 0)) for item in panier.values())


def enrichir_panier(panier):
    """
    Ajoute un champ 'sous_total' à chaque item du panier.
    Utile pour l'affichage dans les templates.
    """
    for item in panier.values():
        prix = Decimal(str(item.get("prix", 0)))
        qte = int(item.get("quantité", 0))
        item["sous_total"] = prix * qte
    return panier
