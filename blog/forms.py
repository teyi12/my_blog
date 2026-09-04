from django import forms
from django.utils.translation import gettext_lazy as _


class ContactForm(forms.Form):
    # https://docs.djangoproject.com/en/3.1/ref/forms/fields/
    nom = forms.CharField(max_length=200, label=_("Nom"))
    prenom = forms.CharField(max_length=200, label=_("Prénom"))
    email = forms.EmailField(label=_("Adresse e-mail"))
    message = forms.CharField(label=_("Message"), widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.label_suffix = ""
