from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from payments.cancellations import (
    OrderCancellationNotAllowed,
    PaidOrderCancellationNotAllowed,
    cancel_order,
    order_can_be_canceled,
)

from .models import Commande, OrderCancellation
from .services import SQLiteLockRetryExhausted, execute_with_sqlite_lock_retry


def _staff_required(user):
    return user.is_authenticated and user.is_staff


def _confirmation_context(order, *, staff_action):
    cancellation = OrderCancellation.objects.filter(commande=order).first()
    return {
        "commande": order,
        "cancellation": cancellation,
        "can_cancel": order_can_be_canceled(order),
        "staff_action": staff_action,
        "requires_refund": order.payment_status == "SUCCESS",
    }


@user_passes_test(_staff_required)
@require_GET
def confirmer_annulation_staff(request, pk):
    order = get_object_or_404(Commande.objects.select_related("client"), pk=pk)
    return render(
        request,
        "shop/commandes/cancel_confirm.html",
        _confirmation_context(order, staff_action=True),
    )


@login_required
@require_GET
def confirmer_annulation_client(request, pk):
    order = get_object_or_404(
        Commande.objects.select_related("client"),
        pk=pk,
        client=request.user,
    )
    return render(
        request,
        "shop/commandes/cancel_confirm.html",
        _confirmation_context(order, staff_action=False),
    )


def _perform_cancellation(request, order, source, redirect_name):
    try:
        outcome = execute_with_sqlite_lock_retry(
            lambda: cancel_order(order.pk, request.user, source)
        )
    except PaidOrderCancellationNotAllowed:
        messages.warning(
            request,
            _(
                "Une commande payée ne peut pas être annulée directement. "
                "Utilisez le remboursement sécurisé."
            ),
        )
    except OrderCancellationNotAllowed:
        messages.warning(
            request,
            _("Cette commande ne peut plus être annulée."),
        )
    except SQLiteLockRetryExhausted:
        messages.error(
            request,
            _("L’annulation est momentanément indisponible. Veuillez réessayer."),
        )
    else:
        if not outcome.created:
            messages.info(request, _("Cette commande est déjà annulée."))
        elif outcome.cancellation.stripe_expiration_status == "FAILED":
            messages.warning(
                request,
                _(
                    "La commande est annulée, mais la session Stripe n’a pas pu "
                    "être expirée. Aucun nouveau paiement ne sera appliqué localement."
                ),
            )
        else:
            messages.success(request, _("La commande a été annulée."))
    return redirect(redirect_name, pk=order.pk)


@user_passes_test(_staff_required)
@require_POST
def annuler_commande_staff(request, pk):
    order = get_object_or_404(Commande, pk=pk)
    return _perform_cancellation(
        request,
        order,
        "STAFF",
        "shop:commande_gestion_detail",
    )


@login_required
@require_POST
def annuler_commande_client(request, pk):
    order = get_object_or_404(Commande, pk=pk, client=request.user)
    return _perform_cancellation(
        request,
        order,
        "CUSTOMER",
        "shop:ma_commande_detail",
    )
