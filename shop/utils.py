from .models import Cart, CartItem, Produit, Commande, LigneCommande

def get_or_create_cart(request):
    """
    Récupère le panier de l'utilisateur connecté, ou crée un panier anonyme (session).
    """
    if request.user.is_authenticated:
        cart, created = Cart.objects.get_or_create(user=request.user)
        return cart
    else:
        # pour utilisateurs non connectés, on stocke cart_id en session
        cart_id = request.session.get("cart_id")
        if cart_id:
            try:
                return Cart.objects.get(id=cart_id, user=None)
            except Cart.DoesNotExist:
                pass
        cart = Cart.objects.create(user=None)
        request.session["cart_id"] = cart.id
        return cart


def add_to_cart(request, produit_id, quantite=1):
    """
    Ajoute un produit au panier
    """
    cart = get_or_create_cart(request)
    produit = Produit.objects.get(id=produit_id)

    item, created = CartItem.objects.get_or_create(
        cart=cart,
        produit=produit,
        defaults={"quantite": quantite, "prix_unitaire": produit.prix}
    )
    if not created:
        item.quantite += quantite
        item.save()
    return cart


def cart_to_commande(cart, user, adresse=None):
    """
    Convertit un panier en commande.
    """
    commande = Commande.objects.create(client=user, adresse=adresse, total=0)
    for item in cart.items.all():
        LigneCommande.objects.create(
            commande=commande,
            produit=item.produit,
            quantite=item.quantite,
            prix_unitaire=item.prix_unitaire,
        )
    commande.recalculate_total()
    cart.delete()  # vider le panier après validation
    return commande
