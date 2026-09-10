from decimal import Decimal

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from payments.subscriptions import (
    SubscriptionAlreadyActive,
    SubscriptionConflict,
    SubscriptionInitializationInProgress,
    SubscriptionProviderError,
    SubscriptionUnavailable,
    get_current_user_subscription,
    initialize_subscription_checkout,
    subscription_has_premium_access,
    subscription_portal_is_available,
    subscriptions_are_available,
)

from .forms import AffiliationForm, PartenariatForm
from .models import Abonnement, Publicite, Revenu


@staff_member_required(login_url="home")
def dashboard_view(request):
    """Dashboard interne basé uniquement sur les revenus réellement enregistrés."""
    totals = {
        row["type"]: row["total"] or Decimal("0")
        for row in Revenu.objects.values("type").annotate(total=Sum("montant"))
    }

    context = {
        "totaux": {
            "publicite": totals.get("PUB", Decimal("0")),
            "affiliation": totals.get("AFF", Decimal("0")),
            "premium": totals.get("SUB", Decimal("0")),
            "dons": totals.get("DON", Decimal("0")),
            "global": sum(totals.values(), Decimal("0")),
        },
        "revenus_recents": Revenu.objects.order_by("-date")[:8],
    }
    return render(request, "monetization/dashboard.html", context)


def partenariat_view(request):
    if request.method == "POST":
        form = PartenariatForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                _("Votre demande de partenariat a été envoyée avec succès."),
            )
            return redirect("monetization:partenariat")
    else:
        form = PartenariatForm()
    return render(request, "monetization/partenariat.html", {"form": form})


def affiliation_view(request):
    if request.method == "POST":
        form = AffiliationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                _("Votre demande d’affiliation a été envoyée avec succès."),
            )
            return redirect("monetization:affiliation")
    else:
        form = AffiliationForm()
    return render(request, "monetization/affiliation.html", {"form": form})


def abonnements_view(request):
    current_subscription = get_current_user_subscription(request.user)
    subscription_blocks_checkout = bool(
        current_subscription
        and current_subscription.status in current_subscription.OPEN_STATUSES
    )
    abonnements = list(Abonnement.objects.all().order_by("prix", "nom"))
    for abonnement in abonnements:
        abonnement.stripe_subscription_available = (
            not subscription_blocks_checkout
            and subscriptions_are_available(abonnement)
        )
    return render(
        request,
        "monetization/abonnements.html",
        {
            "abonnements": abonnements,
            "current_subscription": current_subscription,
            "subscription_access_active": subscription_has_premium_access(
                current_subscription
            ),
            "subscription_blocks_checkout": subscription_blocks_checkout,
            "subscription_portal_available": subscription_portal_is_available(
                current_subscription
            ),
        },
    )


@login_required
@require_POST
def souscrire_abonnement(request, slug):
    """Initialise un Checkout sans jamais activer directement l'accès Premium."""
    abonnement = get_object_or_404(Abonnement, slug=slug)
    try:
        subscription = initialize_subscription_checkout(request, abonnement)
        return redirect(subscription.checkout_url, code=303)
    except SubscriptionUnavailable:
        messages.info(
            request,
            _(
                "La souscription sécurisée à cette formule est actuellement "
                "indisponible. Aucun paiement n’a été déclenché."
            ),
        )
    except SubscriptionAlreadyActive:
        messages.info(
            request,
            _("Vous disposez déjà d’un accès Premium actif."),
        )
    except SubscriptionInitializationInProgress:
        messages.info(
            request,
            _(
                "L’initialisation de votre souscription est déjà en cours. "
                "Veuillez réessayer dans quelques instants."
            ),
        )
    except SubscriptionConflict:
        messages.info(
            request,
            _(
                "Une souscription est déjà en cours pour votre compte. "
                "Aucun nouveau paiement n’a été déclenché."
            ),
        )
    except SubscriptionProviderError:
        messages.error(
            request,
            _(
                "La souscription n’a pas pu être initialisée. "
                "Aucun accès Premium n’a été activé."
            ),
        )
    return redirect("monetization:abonnements")


def don_view(request):
    """La collecte du don est déléguée au checkout Stripe sécurisé de payments."""
    return render(request, "monetization/don.html")


def paiement_view(request):
    return redirect("payments:choice")


def publicite_view(request):
    publicites = (
        Publicite.objects.select_related("partenaire")
        .filter(actif=True)
        .order_by("-date_debut")
    )
    return render(request, "monetization/publicites.html", {"publicites": publicites})
