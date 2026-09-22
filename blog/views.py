import logging
from smtplib import SMTPException

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from articles.models import Article
from monetization.models import Publicite
from shop.models import Produit
from videos.models import Video
from .forms import ContactForm
from .home_media import home_hero_image_url


logger = logging.getLogger(__name__)


def home_view(request):
    publicites = list(
        Publicite.objects.diffusables().select_related("partenaire")[:5]
    )
    articles_recents = list(
        Article.objects.select_related("auteur", "categorie").order_by(
            "-en_vedette",
            F("ordre_affichage").asc(nulls_last=True),
            "-date_publication",
            "-pk",
        )[:3]
    )
    videos_recentes = list(
        Video.objects.select_related("auteur", "categorie")
        .filter(est_publie=True)
        .order_by(
            "-en_vedette",
            F("ordre_affichage").asc(nulls_last=True),
            "-date_publication",
            "-pk",
        )[:2]
    )
    produits_vedettes = list(
        Produit.objects.select_related("categorie")
        .filter(en_vedette=True)
        .order_by("-pk")[:6]
    )
    return render(
        request,
        "home.html",
        {
            "articles_recents": articles_recents,
            "videos_recentes": videos_recentes,
            "produits_vedettes": produits_vedettes,
            "publicites": publicites,
            "hero_image_url": home_hero_image_url(),
        },
    )


def contact_view(request):
    form = ContactForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        nom = form.cleaned_data["nom"]
        prenom = form.cleaned_data["prenom"]
        email = form.cleaned_data["email"]
        message = form.cleaned_data["message"]

        recipient = (getattr(settings, "CONTACT_EMAIL", "") or "").strip()
        from_email = (getattr(settings, "DEFAULT_FROM_EMAIL", "") or "").strip()

        if not recipient or not from_email:
            logger.error(
                "operation=contact_email_configuration_invalid "
                "contact_email_configured=%s default_from_email_configured=%s",
                bool(recipient),
                bool(from_email),
            )
            messages.error(
                request,
                _("Le service de contact est momentanément indisponible. Merci de réessayer plus tard."),
            )
            return render(request, "contact.html", {"form": form}, status=503)

        email_message = EmailMessage(
            subject=f"Contact Teyilawson — {prenom} {nom}",
            body=message,
            from_email=from_email,
            to=[recipient],
            reply_to=[email],
        )

        try:
            email_message.send(fail_silently=False)
        except (SMTPException, OSError) as exc:
            logger.error(
                "operation=contact_email_delivery_failed exception_type=%s",
                type(exc).__name__,
            )
            messages.error(
                request,
                _("L’envoi du message a momentanément échoué. Merci de réessayer dans quelques instants."),
            )
            return render(request, "contact.html", {"form": form}, status=503)

        messages.success(request, _("Votre message a bien été envoyé. Merci pour votre prise de contact."))
        return redirect("contact")

    return render(request, "contact.html", {"form": form})


def remerciement_view(request):
    return HttpResponse(_("Merci pour votre message."))


def about(request):
    return render(request, "about.html")
