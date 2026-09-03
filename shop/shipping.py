import logging
from urllib.parse import quote_plus

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)


def carrier_tracking_url(carrier, tracking_number):
    """Return an official carrier tracking URL when the carrier is recognized."""
    carrier_name = (carrier or "").strip().lower()
    tracking = (tracking_number or "").strip()
    if not tracking:
        return ""

    encoded = quote_plus(tracking)
    if "dhl" in carrier_name:
        return f"https://www.dhl.de/de/privatkunden/dhl-sendungsverfolgung.html?piececode={encoded}"
    if "ups" in carrier_name:
        return f"https://www.ups.com/track?loc=de_DE&tracknum={encoded}"
    if "deutsche post" in carrier_name or carrier_name in {"post", "deutschepost"}:
        return "https://www.deutschepost.de/de/s/sendungsverfolgung.html"
    return ""


def _customer_order_url(commande, request=None):
    path = reverse("shop:ma_commande_detail", kwargs={"pk": commande.pk})
    if request is not None:
        return request.build_absolute_uri(path)
    base_url = getattr(settings, "SITE_BASE_URL", "").strip().rstrip("/")
    return f"{base_url}{path}" if base_url else ""


def send_fulfillment_notification(commande, new_status, request=None):
    """Send a best-effort customer email after a shipping status change."""
    recipient = (commande.client.email or "").strip()
    if not recipient or new_status not in {"SHIPPED", "DELIVERED"}:
        return False

    detail_url = _customer_order_url(commande, request=request)
    tracking_url = carrier_tracking_url(commande.carrier, commande.tracking_number)
    customer_name = commande.client.first_name or "cher client"
    lignes = list(commande.lignes.select_related("produit").all())

    if new_status == "SHIPPED":
        subject = f"Votre commande #{commande.pk} a été expédiée"
        lines = [
            f"Bonjour {customer_name},",
            "",
            f"Votre commande #{commande.pk} a été expédiée.",
        ]
        if commande.carrier:
            lines.append(f"Transporteur : {commande.carrier}")
        if commande.tracking_number:
            lines.append(f"Numéro de suivi : {commande.tracking_number}")
        if tracking_url:
            lines.append(f"Suivre le colis : {tracking_url}")
    else:
        subject = f"Votre commande #{commande.pk} a été livrée"
        lines = [
            f"Bonjour {customer_name},",
            "",
            f"Votre commande #{commande.pk} est indiquée comme livrée.",
        ]

    if detail_url:
        lines.extend(["", f"Consulter votre commande : {detail_url}"])
    lines.extend(["", "Merci pour votre confiance.", "L'équipe My Blog Shop"])

    sender = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None)
    if not sender:
        logger.warning("Shipping email skipped for order %s: no sender configured", commande.pk)
        return False

    html_body = render_to_string(
        "shop/emails/fulfillment_status.html",
        {
            "subject": subject,
            "commande": commande,
            "new_status": new_status,
            "customer_name": customer_name,
            "tracking_url": tracking_url,
            "detail_url": detail_url,
            "lignes": lignes,
        },
    )

    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body="\n".join(lines),
            from_email=sender,
            to=[recipient],
        )
        message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)
    except Exception:
        logger.exception("Unable to send fulfillment email for order %s", commande.pk)
        return False
    return True
