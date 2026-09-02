import json
import stripe
import uuid
from decimal import Decimal
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView, View
from django.urls import reverse, reverse_lazy
from django.contrib import messages

from .models import Produit, Categorie, Cart, CartItem, Commande, LigneCommande
from payments.models import Adresse
from .forms import AdresseForm
from .services import SQLiteLockRetryExhausted, execute_with_sqlite_lock_retry

# --- STRIPE ---
stripe.api_key = settings.STRIPE_SECRET_KEY


# ================= PANIER =================
@login_required
def panier_view(request):
    cart, _ = Cart.objects.get_or_create(user=request.user)
    return render(request, "shop/panier.html", {"cart": cart})


@login_required
def update_panier(request):
    if request.method != "POST":
        return JsonResponse({"success": False}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))
        action = data.get("action")
        item_id = data.get("item_id")
        quantite = int(data.get("quantite", 1))

        cart, _ = Cart.objects.get_or_create(user=request.user)

        if action == "modifier" and item_id:
            item = get_object_or_404(CartItem, id=item_id, cart=cart)
            item.quantite = max(1, quantite)
            item.save()
        elif action == "supprimer" and item_id:
            item = get_object_or_404(CartItem, id=item_id, cart=cart)
            item.delete()
        else:
            return JsonResponse({"success": False}, status=400)

        # Sous-totaux de tous les items
        sous_totaux = {i.id: float(i.sous_total()) for i in cart.items.all()}

        return JsonResponse({
            "success": True,
            "total": float(cart.total()),
            "total_articles": cart.total_articles(),
            "sous_totaux": sous_totaux
        })
    except Exception as e:
        print("Erreur update_panier:", e)
        return JsonResponse({"success": False}, status=400)


@login_required
def ajouter_panier(request, slug):
    produit = get_object_or_404(Produit, slug=slug)
    cart, _ = Cart.objects.get_or_create(user=request.user)

    item, created = CartItem.objects.get_or_create(cart=cart, produit=produit)
    if not created:
        CartItem.objects.filter(pk=item.pk).update(quantite=F("quantite") + 1)

    return redirect("shop:panier")


# ================= PRODUITS =================
class ProduitListView(ListView):
    model = Produit
    template_name = "shop/liste.html"
    context_object_name = "produits"
    paginate_by = 12


class ProduitDetailView(DetailView):
    model = Produit
    template_name = "shop/detail.html"
    context_object_name = "produit"
    slug_field = "slug"
    slug_url_kwarg = "slug"


def produits_par_categorie(request, slug):
    categorie = get_object_or_404(Categorie, slug=slug)
    produits = Produit.objects.filter(categorie=categorie)
    return render(request, "shop/liste.html", {"produits": produits, "categorie": categorie})


import stripe
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.http import HttpResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.urls import reverse_lazy

from shop.models import Cart, Commande, LigneCommande
from payments.models import Adresse
from .forms import AdresseForm

stripe.api_key = settings.STRIPE_SECRET_KEY


# ================= CHECKOUT =================
class CheckoutView(LoginRequiredMixin, View):
    """Affichage du formulaire d’adresse et sauvegarde"""

    def get(self, request, *args, **kwargs):
        cart = Cart.objects.filter(user=request.user).first()
        if not cart or not cart.items.exists():
            messages.warning(request, "Votre panier est vide.")
            return redirect("shop:panier")

        form = AdresseForm()
        return render(request, "shop/checkout.html", {
            "cart": cart,
            "total": cart.total(),
            "form": form,
            "checkout_token": uuid.uuid4(),
        })

    def post(self, request, *args, **kwargs):
        """Crée l'adresse et la commande correspondant au panier validé."""
        form = AdresseForm(request.POST)
        try:
            checkout_token = uuid.UUID(request.POST.get("checkout_token", ""))
        except (TypeError, ValueError):
            messages.error(request, "Session de checkout invalide. Veuillez réessayer.")
            return redirect("shop:checkout")

        if form.is_valid():
            address_data = {
                field: form.cleaned_data[field]
                for field in ("rue", "ville", "code_postal", "pays", "telephone")
            }

            def create_order():
                with transaction.atomic():
                    existing = Commande.objects.filter(
                        client=request.user,
                        checkout_token=checkout_token,
                    ).first()
                    if existing:
                        return existing

                    cart = (
                        Cart.objects.select_for_update()
                        .filter(user=request.user)
                        .first()
                    )
                    if not cart:
                        return None

                    items = list(
                        cart.items.select_for_update().select_related("produit")
                    )
                    if not items:
                        return None

                    adresse = Adresse.objects.create(
                        utilisateur=request.user,
                        **address_data,
                    )
                    total = sum(
                        (item.produit.prix * item.quantite for item in items),
                        Decimal("0.00"),
                    )
                    commande = Commande.objects.create(
                        client=request.user,
                        adresse=adresse,
                        source_cart=cart,
                        checkout_token=checkout_token,
                        total=total,
                        currency=getattr(settings, "DEFAULT_CURRENCY", "EUR"),
                        payment_status="PENDING",
                    )
                    LigneCommande.objects.bulk_create(
                        [
                            LigneCommande(
                                commande=commande,
                                produit=item.produit,
                                source_cart_item=item,
                                quantite=item.quantite,
                                prix_unitaire=item.produit.prix,
                            )
                            for item in items
                        ]
                    )
                    return commande

            try:
                commande = execute_with_sqlite_lock_retry(create_order)
            except IntegrityError:
                commande = Commande.objects.filter(
                    client=request.user,
                    checkout_token=checkout_token,
                ).first()
                if not commande:
                    raise
            except SQLiteLockRetryExhausted:
                try:
                    commande = execute_with_sqlite_lock_retry(
                        lambda: Commande.objects.filter(
                            client=request.user,
                            checkout_token=checkout_token,
                        ).first()
                    )
                except SQLiteLockRetryExhausted:
                    commande = None

                if not commande:
                    cart = Cart.objects.filter(user=request.user).first()
                    messages.warning(
                        request,
                        "Le checkout est momentanément occupé. Veuillez réessayer.",
                    )
                    return render(request, "shop/checkout.html", {
                        "cart": cart,
                        "total": cart.total() if cart else Decimal("0.00"),
                        "form": form,
                        "checkout_token": checkout_token,
                    }, status=409)

            if not commande:
                messages.warning(request, "Votre panier est vide.")
                return redirect("shop:panier")

            url = reverse("shop:adresse_enregistree")
            return redirect(f"{url}?order_id={commande.id}")

        cart = Cart.objects.filter(user=request.user).first()
        if not cart or not cart.items.exists():
            messages.warning(request, "Votre panier est vide.")
            return redirect("shop:panier")

        return render(request, "shop/checkout.html", {
            "cart": cart,
            "total": cart.total(),
            "form": form,
            "checkout_token": checkout_token,
        })


# ================= PAGE "ADRESSE ENREGISTRÉE" =================
@login_required
def adresse_enregistree(request):
    """Affiche un message de confirmation puis redirige vers le choix du paiement"""
    commande = get_object_or_404(
        Commande,
        id=request.GET.get("order_id"),
        client=request.user,
        payment_status="PENDING",
    )
    return render(
        request,
        "shop/adresse_enregistree.html",
        {"commande": commande},
    )


# ================= CONFIRMATION COMMANDE =================
from django.views.generic import DetailView

class ConfirmationView(LoginRequiredMixin, DetailView):
    model = Commande
    template_name = "shop/confirmation.html"
    context_object_name = "commande"

    def get_queryset(self):
        return Commande.objects.filter(client=self.request.user)
