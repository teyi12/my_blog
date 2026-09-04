from django import forms
from django.utils.translation import gettext_lazy as _


REQUIRED_ERROR = _("Ce champ est obligatoire.")


class ContactForm(forms.Form):
    # https://docs.djangoproject.com/en/3.1/ref/forms/fields/
    nom = forms.CharField(
        max_length=200,
        label=_("Nom"),
        error_messages={"required": REQUIRED_ERROR},
    )
    prenom = forms.CharField(
        max_length=200,
        label=_("Prénom"),
        error_messages={"required": REQUIRED_ERROR},
    )
    email = forms.EmailField(
        label=_("Adresse e-mail"),
        error_messages={"required": REQUIRED_ERROR},
    )
    message = forms.CharField(
        label=_("Message"),
        widget=forms.Textarea,
        error_messages={"required": REQUIRED_ERROR},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.label_suffix = ""
