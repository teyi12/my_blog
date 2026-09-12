import logging
from urllib.parse import quote_plus

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _

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

    sender = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None)
    if not sender:
        logger.warning("Shipping email skipped for order %s: no sender configured", commande.pk)
        return False

    language_code = commande.language_code or "fr"
    with translation.override(language_code):
        detail_url = _customer_order_url(commande, request=request)
        tracking_url = carrier_tracking_url(commande.carrier, commande.tracking_number)
        customer_name = commande.client.first_name or _("cher client")
        lignes = list(commande.lignes.select_related("produit").all())

        if new_status == "SHIPPED":
            subject = _("Votre commande #%(order)s a été expédiée") % {"order": commande.pk}
            lines = [
                _("Bonjour %(name)s,") % {"name": customer_name},
                "",
                _("Votre commande #%(order)s a été expédiée.") % {"order": commande.pk},
            ]
            if commande.carrier:
                lines.append(_("Transporteur : %(carrier)s") % {"carrier": commande.carrier})
            if commande.tracking_number:
                lines.append(_("Numéro de suivi : %(tracking)s") % {"tracking": commande.tracking_number})
            if tracking_url:
                lines.append(_("Suivre le colis : %(url)s") % {"url": tracking_url})
        else:
            subject = _("Votre commande #%(order)s a été livrée") % {"order": commande.pk}
            lines = [
                _("Bonjour %(name)s,") % {"name": customer_name},
                "",
                _("Votre commande #%(order)s est indiquée comme livrée.") % {"order": commande.pk},
            ]

        if detail_url:
            lines.extend(["", _("Consulter votre commande : %(url)s") % {"url": detail_url}])
        lines.extend(["", _("Merci pour votre confiance."), _("L'équipe My Blog Shop")])

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
                "email_language": language_code,
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
        except Exception as exc:
            logger.warning(
                "operation=fulfillment_notification exception_type=%s order_id=%s",
                type(exc).__name__,
                commande.pk,
            )
            return False
    return True
