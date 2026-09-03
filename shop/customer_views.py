from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from .models import Commande
from .shipping import carrier_tracking_url


@login_required
def mes_commandes(request):
    commandes = (
        Commande.objects.filter(client=request.user)
        .prefetch_related("lignes__produit")
        .order_by("-date_commande")
    )
    paginator = Paginator(commandes, 10)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "shop/client/mes_commandes.html",
        {"commandes": page_obj.object_list, "page_obj": page_obj},
    )


@login_required
def ma_commande_detail(request, pk):
    commande = get_object_or_404(
        Commande.objects.filter(client=request.user)
        .select_related("adresse")
        .prefetch_related("lignes__produit", "payments"),
        pk=pk,
    )
    return render(
        request,
        "shop/client/commande_detail.html",
        {
            "commande": commande,
            "paiements": commande.payments.order_by("-created_at"),
            "tracking_url": carrier_tracking_url(commande.carrier, commande.tracking_number),
        },
    )
