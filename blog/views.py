from smtplib import SMTPException

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.http import HttpResponse
from django.shortcuts import redirect, render

from shop.models import Produit
from .forms import ContactForm


def home_view(request):
    produits_vedettes = Produit.objects.filter(en_vedette=True)[:6]
    return render(request, "home.html", {"produits_vedettes": produits_vedettes})


def contact_view(request):
    form = ContactForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        nom = form.cleaned_data["nom"]
        prenom = form.cleaned_data["prenom"]
        email = form.cleaned_data["email"]
        message = form.cleaned_data["message"]

        recipient = getattr(settings, "CONTACT_EMAIL", None) or settings.EMAIL_HOST_USER
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or settings.EMAIL_HOST_USER

        if not recipient or not from_email:
            messages.error(
                request,
                "Le service de contact est momentanément indisponible. Merci de réessayer plus tard.",
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
        except (SMTPException, OSError):
            messages.error(
                request,
                "L’envoi du message a momentanément échoué. Merci de réessayer dans quelques instants.",
            )
            return render(request, "contact.html", {"form": form}, status=503)

        messages.success(request, "Votre message a bien été envoyé. Merci pour votre prise de contact.")
        return redirect("contact")

    return render(request, "contact.html", {"form": form})


def remerciement_view(request):
    return HttpResponse("Merci pour votre message.")


def about(request):
    return render(request, "about.html")
