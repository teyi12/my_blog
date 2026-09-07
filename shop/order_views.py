from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.utils.translation import gettext as _

from .forms import CommandeExpeditionForm
from .models import Commande


def _staff_required(user):
    return user.is_authenticated and user.is_staff


@user_passes_test(_staff_required)
@require_http_methods(["GET", "POST"])
def commande_expedition_modifier(request, pk):
    commande = get_object_or_404(Commande, pk=pk)

    if commande.fulfillment_status not in {"SHIPPED", "DELIVERED"}:
        messages.warning(
            request,
            _("Les informations d’expédition peuvent être modifiées uniquement après l’expédition de la commande."),
        )
        return redirect("shop:commande_gestion_detail", pk=commande.pk)

    form = CommandeExpeditionForm(request.POST or None, instance=commande)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(
            request,
            _("Les informations d’expédition de la commande #%(order)s ont été mises à jour.")
            % {"order": commande.pk},
        )
        return redirect("shop:commande_gestion_detail", pk=commande.pk)

    return render(
        request,
        "shop/commandes/expedition_form.html",
        {"commande": commande, "form": form},
    )
