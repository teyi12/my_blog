import json
import stripe
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView, View
from django.urls import reverse, reverse_lazy
from django.contrib import messages

from .models import Produit, Categorie, Cart, CartItem, Commande, LigneCommande
from payments.models import Adresse
from .forms import AdresseForm, CategorieForm
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
    return render(request, "shop/produits_par_categorie.html", {"produits": produits, "categorie": categorie})


# ================= GESTION DES CATÉGORIES =================
def _staff_required(user):
    return user.is_authenticated and user.is_staff


@user_passes_test(_staff_required)
def categorie_gestion_liste(request):
    categories = Categorie.objects.annotate(nombre_produits=Count("produit")).order_by("nom")
    return render(request, "shop/categories/liste.html", {"categories": categories})


@user_passes_test(_staff_required)
def categorie_creer(request):
    form = CategorieForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        categorie = form.save()
        messages.success(request, f"La catégorie « {categorie.nom} » a été créée.")
        return redirect("shop:categorie_gestion_liste")
    return render(
        request,
        "shop/categories/form.html",
        {"form": form, "mode": "creation"},
    )


@user_passes_test(_staff_required)
def categorie_modifier(request, slug):
    categorie = get_object_or_404(Categorie, slug=slug)
    form = CategorieForm(request.POST or None, instance=categorie)
    if request.method == "POST" and form.is_valid():
        categorie = form.save()
        messages.success(request, f"La catégorie « {categorie.nom} » a été mise à jour.")
        return redirect("shop:categorie_gestion_liste")
    return render(
        request,
        "shop/categories/form.html",
        {"form": form, "categorie": categorie, "mode": "modification"},
    )


@user_passes_test(_staff_required)
def categorie_supprimer(request, slug):
    categorie = get_object_or_404(Categorie, slug=slug)
    nombre_produits = categorie.produit_set.count()
    if request.method == "POST":
        nom = categorie.nom
        categorie.delete()
        if nombre_produits:
            messages.warning(
                request,
                f"La catégorie « {nom} » a été supprimée. {nombre_produits} produit(s) sont maintenant sans catégorie.",
            )
        else:
            messages.success(request, f"La catégorie « {nom} » a été supprimée.")
        return redirect("shop:categorie_gestion_liste")
    return render(
        request,
        "shop/categories/supprimer.html",
        {"categorie": categorie, "nombre_produits": nombre_produits},
    )


# ================= GESTION DES COMMANDES =================
@user_passes_test(_staff_required)
def commande_gestion_liste(request):
    commandes = (
        Commande.objects.select_related("client", "adresse")
        .prefetch_related("lignes")
        .order_by("-date_commande")
    )

    statut = request.GET.get("statut", "").strip().upper()
    recherche = request.GET.get("q", "").strip()
    statuts_valides = {value for value, _label in Commande._meta.get_field("payment_status").choices}

    if statut in statuts_valides:
        commandes = commandes.filter(payment_status=statut)
    else:
        statut = ""

    if recherche:
        filtre = (
            Q(client__email__icontains=recherche)
            | Q(client__first_name__icontains=recherche)
            | Q(client__last_name__icontains=recherche)
            | Q(transaction_id__icontains=recherche)
        )
        if recherche.isdigit():
            filtre |= Q(pk=int(recherche))
        commandes = commandes.filter(filtre).distinct()

    compteurs = {
        "ALL": Commande.objects.count(),
        "PENDING": Commande.objects.filter(payment_status="PENDING").count(),
        "PROCESSING": Commande.objects.filter(payment_status="PROCESSING").count(),
        "SUCCESS": Commande.objects.filter(payment_status="SUCCESS").count(),
        "FAILED": Commande.objects.filter(payment_status="FAILED").count(),
        "CANCELED": Commande.objects.filter(payment_status="CANCELED").count(),
    }

    paginator = Paginator(commandes, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "shop/commandes/liste.html",
        {
            "page_obj": page_obj,
            "commandes": page_obj.object_list,
            "statut_actif": statut,
            "recherche": recherche,
            "compteurs": compteurs,
        },
    )


@user_passes_test(_staff_required)
def commande_gestion_detail(request, pk):
    commande = get_object_or_404(
        Commande.objects.select_related("client", "adresse")
        .prefetch_related("lignes__produit", "payments"),
        pk=pk,
    )
    paiements = commande.payments.order_by("-created_at")
    return render(
        request,
        "shop/commandes/detail.html",
        {"commande": commande, "paiements": paiements},
    )


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
class ConfirmationView(LoginRequiredMixin, DetailView):
    model = Commande
    template_name = "shop/confirmation.html"
    context_object_name = "commande"

    def get_queryset(self):
        return Commande.objects.filter(client=self.request.user)
