from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from shop.models import Commande

from .models import StripeOrderRefund
from .refunds import (
    RefundAlreadyCompleted,
    RefundInProgress,
    RefundMismatch,
    RefundNotAllowed,
    RefundProviderError,
    get_refundable_payment,
    request_full_refund,
)


def _staff_required(user):
    return user.is_authenticated and user.is_staff


def _refund_for_order(order):
    return StripeOrderRefund.objects.filter(commande=order).first()


@user_passes_test(_staff_required)
@require_GET
def confirmer_remboursement_commande(request, pk):
    order = get_object_or_404(
        Commande.objects.select_related("client"),
        pk=pk,
    )
    payment = get_refundable_payment(order)
    refund = _refund_for_order(order)
    if payment is None or (
        refund is not None and refund.status != "RETRYABLE"
    ):
        messages.warning(
            request,
            _("Cette commande ne peut pas être remboursée."),
        )
        return redirect("shop:commande_gestion_detail", pk=order.pk)

    return render(
        request,
        "payments/order_refund_confirm.html",
        {"commande": order, "refund": refund},
    )


@user_passes_test(_staff_required)
@require_POST
def rembourser_commande(request, pk):
    order = get_object_or_404(Commande, pk=pk)
    try:
        refund = request_full_refund(order.pk, request.user.pk)
    except RefundAlreadyCompleted:
        messages.info(request, _("Cette commande est déjà remboursée."))
    except RefundInProgress:
        messages.info(
            request,
            _("Le remboursement de cette commande est déjà en cours."),
        )
    except RefundNotAllowed:
        messages.warning(
            request,
            _("Cette commande ne peut pas être remboursée."),
        )
    except RefundProviderError:
        messages.error(
            request,
            _(
                "Stripe est temporairement indisponible. "
                "Le remboursement peut être relancé sans risque."
            ),
        )
    except RefundMismatch:
        messages.error(
            request,
            _(
                "Le remboursement n’a pas été validé car les données Stripe "
                "ne correspondent pas à la commande."
            ),
        )
    else:
        if refund.status == "SUCCESS":
            messages.success(
                request,
                _("Le remboursement total a été confirmé par Stripe."),
            )
        elif refund.status == "PENDING":
            messages.info(
                request,
                _("Le remboursement est en attente de confirmation par Stripe."),
            )
        else:
            messages.error(
                request,
                _("Stripe n’a pas confirmé le remboursement."),
            )
    return redirect("shop:commande_gestion_detail", pk=order.pk)
