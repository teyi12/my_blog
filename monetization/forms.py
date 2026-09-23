from django import forms
from django.utils.translation import gettext_lazy as _, pgettext_lazy

from .models import DemandePartenariat, DemandeAffiliation


REQUIRED_ERROR = _("Ce champ est obligatoire.")


class AccessibleBoundFormMixin:
    """Connect bound field errors to their controls without changing validation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            return

        for field_name in self.errors:
            if field_name not in self.fields:
                continue
            field = self.fields[field_name]
            field.widget.attrs["aria-invalid"] = "true"
            field.widget.attrs["aria-describedby"] = f"id_{field_name}_errors"


class PartenariatForm(AccessibleBoundFormMixin, forms.ModelForm):
    class Meta:
        model = DemandePartenariat
        fields = ["nom", "email", "entreprise", "message"]
        labels = {
            "nom": pgettext_lazy("monetization form", "Nom"),
            "email": _("Adresse e-mail"),
            "entreprise": _("Entreprise"),
            "message": _("Votre proposition"),
        }
        error_messages = {
            "nom": {"required": REQUIRED_ERROR},
            "email": {"required": REQUIRED_ERROR},
            "message": {"required": REQUIRED_ERROR},
        }


class AffiliationForm(AccessibleBoundFormMixin, forms.ModelForm):
    class Meta:
        model = DemandeAffiliation
        fields = ["nom", "email", "plateforme", "produit", "message"]
        labels = {
            "nom": pgettext_lazy("monetization form", "Nom"),
            "email": _("Adresse e-mail"),
            "plateforme": _("Plateforme"),
            "produit": _("Produit ou service"),
            "message": _("Votre proposition"),
        }
        error_messages = {
            "nom": {"required": REQUIRED_ERROR},
            "email": {"required": REQUIRED_ERROR},
            "plateforme": {"required": REQUIRED_ERROR},
            "produit": {"required": REQUIRED_ERROR},
            "message": {"required": REQUIRED_ERROR},
        }
