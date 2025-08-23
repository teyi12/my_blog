# shop/context_processors.py
from .models import Cart

def panier_counter(request):
    count = 0
    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        if cart:
            count = cart.items.count()
    return {"panier_items_count": count}
