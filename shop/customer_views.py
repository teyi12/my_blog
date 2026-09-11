import logging

from cloudinary.exceptions import Error as CloudinaryError
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET
from requests.exceptions import RequestException

from .models import Commande, LigneCommande, product_file_storage
from .shipping import carrier_tracking_url


logger = logging.getLogger(__name__)

DOWNLOAD_STORAGE_EXCEPTIONS = (CloudinaryError, RequestException, OSError)


def _customer_orders(user):
    """Return orders owned by the authenticated customer only."""
    return Commande.objects.filter(client=user)


@login_required
@require_GET
def mes_commandes(request):
    commandes = (
        _customer_orders(request.user)
        .prefetch_related("lignes__produit")
        .order_by("-date_commande", "-pk")
    )
    paginator = Paginator(commandes, 10)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "shop/client/mes_commandes.html",
        {"commandes": page_obj.object_list, "page_obj": page_obj},
    )


@login_required
@require_GET
def ma_commande_detail(request, pk):
    commande = get_object_or_404(
        _customer_orders(request.user)
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


@login_required
@require_GET
def telecharger_fichier_commande(request, order_pk, line_pk):
    """Stream one paid digital purchase without exposing its storage URL."""
    ligne = get_object_or_404(
        LigneCommande.objects.select_related("commande").filter(
            commande_id=order_pk,
            commande__client=request.user,
        ),
        pk=line_pk,
    )
    if (
        ligne.commande.payment_status != "SUCCESS"
        or not ligne.fichier_nom_stockage_snapshot
    ):
        raise Http404

    storage_name = ligne.fichier_nom_stockage_snapshot
    try:
        file_handle = product_file_storage().open(storage_name, "rb")
    except FileNotFoundError as exc:
        logger.warning(
            "operation=customer_order_file_download exception_type=%s "
            "order_id=%s line_id=%s",
            type(exc).__name__,
            ligne.commande_id,
            ligne.pk,
        )
        raise Http404 from None
    except DOWNLOAD_STORAGE_EXCEPTIONS as exc:
        logger.warning(
            "operation=customer_order_file_download exception_type=%s "
            "order_id=%s line_id=%s",
            type(exc).__name__,
            ligne.commande_id,
            ligne.pk,
        )
        return HttpResponse(
            _(
                "Ce fichier est temporairement indisponible. "
                "Veuillez réessayer ultérieurement."
            ),
            status=503,
        )

    response = FileResponse(
        file_handle,
        as_attachment=True,
        filename=(
            ligne.fichier_nom_telechargement_snapshot or "fichier-commande"
        ),
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
