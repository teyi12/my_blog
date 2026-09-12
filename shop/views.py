import json
import stripe
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.decorators.http import require_POST
from django.views.generic import ListView, DetailView, View
from django.urls import reverse, reverse_lazy
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _, ngettext

from .models import (
    Cart,
    CartItem,
    Categorie,
    Commande,
    LigneCommande,
    Produit,
    order_product_snapshot_name,
    safe_order_download_filename,
)
from payments.models import Adresse, StripeOrderRefund
from blog.seo import PRODUCT_CATEGORY_DESCRIPTION, build_dynamic_seo
from .forms import AdresseForm, CategorieForm, CommandeTraitementForm
from .fulfillment import (
    InvalidFulfillmentTransition,
    PaymentNotConfirmed,
    ShippingDetailsInvalid,
    transition_order_fulfillment,
)
from .inventory import (
    StockUnavailable,
    add_product_to_cart,
    cart_stock_issues,
    lock_and_validate_cart_items,
    remove_cart_item,
    set_cart_item_quantity,
)
from .services import (
    SQLiteLockRetryExhausted,
    execute_with_sqlite_lock_retry,
    get_or_create_active_cart,
)

# --- STRIPE ---
stripe.api_key = settings.STRIPE_SECRET_KEY


# ================= PANIER =================
@login_required
def panier_view(request):
    cart = get_or_create_active_cart(request.user)
    stock_issues = cart_stock_issues(cart)
    return render(
        request,
        "shop/panier.html",
        {
            "cart": cart,
            "stock_issues": stock_issues,
            "cart_has_stock_issue": bool(stock_issues),
        },
    )


@login_required
def update_panier(request):
    if request.method != "POST":
        return JsonResponse({"success": False}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except (TypeError, ValueError, UnicodeDecodeError):
        return JsonResponse({"success": False}, status=400)

    action = data.get("action")
    item_id = data.get("item_id")
    cart = get_or_create_active_cart(request.user)
    try:
        if action == "modifier" and item_id:
            set_cart_item_quantity(
                cart.id,
                item_id,
                data.get("quantite"),
            )
        elif action == "supprimer" and item_id:
            remove_cart_item(cart.id, item_id)
        else:
            return JsonResponse({"success": False}, status=400)
    except StockUnavailable as exc:
        return JsonResponse(
            {
                "success": False,
                "error": _("Stock insuffisant."),
                "available": exc.available,
            },
            status=409,
        )
    except (Cart.DoesNotExist, CartItem.DoesNotExist, Produit.DoesNotExist, ValueError):
        return JsonResponse({"success": False}, status=400)

    sous_totaux = {i.id: float(i.sous_total()) for i in cart.items.all()}
    return JsonResponse({
        "success": True,
        "total": float(cart.total()),
        "total_articles": cart.total_articles(),
        "sous_totaux": sous_totaux,
    })


@require_POST
@login_required
def ajouter_panier(request, slug):
    produit = get_object_or_404(Produit, slug=slug)
    cart = get_or_create_active_cart(request.user)

    try:
        add_product_to_cart(cart.id, produit.id)
    except StockUnavailable as exc:
        if exc.available == 0:
            messages.warning(request, _("Rupture de stock."))
        else:
            messages.warning(
                request,
                _("Quantité disponible : %(available)s.")
                % {"available": exc.available},
            )
        return redirect("shop:panier")

    messages.success(
        request,
        _("« %(product)s » a été ajouté à votre panier.") % {"product": produit.nom},
    )

    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("shop:panier")


# ================= PRODUITS =================
class ProduitListView(ListView):
    model = Produit
    queryset = Produit.objects.select_related("categorie").order_by("pk")
    template_name = "shop/liste.html"
    context_object_name = "produits"
    paginate_by = 12


class ProduitDetailView(DetailView):
    model = Produit
    template_name = "shop/detail.html"
    context_object_name = "produit"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["seo"] = build_dynamic_seo(
            self.request,
            instance=self.object,
            view_name="shop:detail",
            kwargs={"slug": self.object.slug},
            title_field="nom",
            description_field="description",
            required_fields=("nom", "description"),
            image_field="image",
        )
        return context


def produits_par_categorie(request, slug):
    categorie = get_object_or_404(Categorie, slug=slug)
    produits = Produit.objects.filter(categorie=categorie).select_related("categorie")
    seo = build_dynamic_seo(
        request,
        instance=categorie,
        view_name="shop:par_categorie",
        kwargs={"slug": categorie.slug},
        title_field="nom",
        default_description=PRODUCT_CATEGORY_DESCRIPTION,
        required_fields=("nom",),
    )
    return render(
        request,
        "shop/produits_par_categorie.html",
        {"produits": produits, "categorie": categorie, "seo": seo},
    )


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
        messages.success(
            request,
            _("La catégorie « %(category)s » a été créée.")
            % {"category": categorie.nom},
        )
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
        messages.success(
            request,
            _("La catégorie « %(category)s » a été mise à jour.")
            % {"category": categorie.nom},
        )
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
                ngettext(
                    "La catégorie « %(category)s » a été supprimée. %(count)s produit est maintenant sans catégorie.",
                    "La catégorie « %(category)s » a été supprimée. %(count)s produits sont maintenant sans catégorie.",
                    nombre_produits,
                )
                % {"category": nom, "count": nombre_produits},
            )
        else:
            messages.success(
                request,
                _("La catégorie « %(category)s » a été supprimée.")
                % {"category": nom},
            )
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
            | Q(tracking_number__icontains=recherche)
            | Q(carrier__icontains=recherche)
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
        "REFUNDED": Commande.objects.filter(payment_status="REFUNDED").count(),
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
    remboursement = StripeOrderRefund.objects.filter(commande=commande).first()
    traitement_form = CommandeTraitementForm(commande=commande)
    transitions_disponibles = bool(traitement_form.fields["statut"].choices)
    return render(
        request,
        "shop/commandes/detail.html",
        {
            "commande": commande,
            "paiements": paiements,
            "remboursement": remboursement,
            "traitement_form": traitement_form,
            "transitions_disponibles": transitions_disponibles,
        },
    )


@user_passes_test(_staff_required)
@require_POST
def commande_traitement_modifier(request, pk):
    commande = get_object_or_404(Commande, pk=pk)
    form = CommandeTraitementForm(request.POST, commande=commande)

    if commande.payment_status != "SUCCESS":
        messages.warning(
            request,
            _("Le traitement logistique ne peut avancer qu’après confirmation du paiement."),
        )
        return redirect("shop:commande_gestion_detail", pk=commande.pk)

    if not form.is_valid():
        messages.error(
            request,
            _(
                "Transition de traitement invalide. "
                "Vérifiez les informations d’expédition."
            ),
        )
        return redirect("shop:commande_gestion_detail", pk=commande.pk)

    nouveau_statut = form.cleaned_data["statut"]
    try:
        commande = transition_order_fulfillment(
            commande.pk,
            nouveau_statut,
            carrier=form.cleaned_data["carrier"],
            tracking_number=form.cleaned_data["tracking_number"],
        )
    except PaymentNotConfirmed:
        messages.warning(
            request,
            _("Le traitement logistique ne peut avancer qu’après confirmation du paiement."),
        )
        return redirect("shop:commande_gestion_detail", pk=commande.pk)
    except (InvalidFulfillmentTransition, ShippingDetailsInvalid):
        messages.error(
            request,
            _("Cette transition de traitement n’est pas autorisée."),
        )
        return redirect("shop:commande_gestion_detail", pk=commande.pk)

    messages.success(
        request,
        _("Le traitement de la commande #%(order)s est maintenant « %(status)s ».")
        % {"order": commande.pk, "status": commande.get_fulfillment_status_display()},
    )
    return redirect("shop:commande_gestion_detail", pk=commande.pk)


# ================= CHECKOUT =================
class CheckoutView(LoginRequiredMixin, View):
    """Affichage du formulaire d’adresse et sauvegarde"""

    def get(self, request, *args, **kwargs):
        cart = Cart.objects.filter(user=request.user, actif=True).first()
        if not cart or not cart.items.exists():
            messages.warning(request, _("Votre panier est vide."))
            return redirect("shop:panier")

        stock_issues = cart_stock_issues(cart)
        form = AdresseForm()
        return render(request, "shop/checkout.html", {
            "cart": cart,
            "total": cart.total(),
            "form": form,
            "checkout_token": uuid.uuid4(),
            "cart_has_stock_issue": bool(stock_issues),
        })

    def post(self, request, *args, **kwargs):
        """Crée l'adresse et la commande correspondant au panier validé."""
        form = AdresseForm(request.POST)
        try:
            checkout_token = uuid.UUID(request.POST.get("checkout_token", ""))
        except (TypeError, ValueError):
            messages.error(request, _("Session de checkout invalide. Veuillez réessayer."))
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
                        .filter(user=request.user, actif=True)
                        .first()
                    )
                    if not cart:
                        return None

                    items = lock_and_validate_cart_items(cart)
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
                        language_code=request.LANGUAGE_CODE,
                    )
                    order_lines = []
                    for item in items:
                        storage_name = (
                            item.produit.fichier.name
                            if item.produit.fichier
                            else ""
                        )
                        order_lines.append(
                            LigneCommande(
                                commande=commande,
                                produit=item.produit,
                                source_cart_item=item,
                                quantite=item.quantite,
                                prix_unitaire=item.produit.prix,
                                nom_produit_snapshot=order_product_snapshot_name(
                                    item.produit,
                                    commande.language_code,
                                ),
                                fichier_nom_stockage_snapshot=storage_name,
                                fichier_nom_telechargement_snapshot=(
                                    safe_order_download_filename(storage_name)
                                ),
                            )
                        )
                    LigneCommande.objects.bulk_create(order_lines)
                    return commande

            try:
                commande = execute_with_sqlite_lock_retry(create_order)
            except StockUnavailable as exc:
                cart = Cart.objects.filter(
                    user=request.user,
                    actif=True,
                ).first()
                messages.error(
                    request,
                    _("Le panier n’est plus disponible. Quantité disponible : %(available)s.")
                    % {"available": exc.available},
                )
                return render(request, "shop/checkout.html", {
                    "cart": cart,
                    "total": cart.total() if cart else Decimal("0.00"),
                    "form": form,
                    "checkout_token": checkout_token,
                    "cart_has_stock_issue": True,
                }, status=409)
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
                    cart = Cart.objects.filter(user=request.user, actif=True).first()
                    messages.warning(
                        request,
                        _("Le checkout est momentanément occupé. Veuillez réessayer."),
                    )
                    return render(request, "shop/checkout.html", {
                        "cart": cart,
                        "total": cart.total() if cart else Decimal("0.00"),
                        "form": form,
                        "checkout_token": checkout_token,
                    }, status=409)

            if not commande:
                messages.warning(request, _("Votre panier est vide."))
                return redirect("shop:panier")

            url = reverse("shop:adresse_enregistree")
            return redirect(f"{url}?order_id={commande.id}")

        cart = Cart.objects.filter(user=request.user, actif=True).first()
        if not cart or not cart.items.exists():
            messages.warning(request, _("Votre panier est vide."))
            return redirect("shop:panier")

        return render(request, "shop/checkout.html", {
            "cart": cart,
            "total": cart.total(),
            "form": form,
            "checkout_token": checkout_token,
            "cart_has_stock_issue": bool(cart_stock_issues(cart)),
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
