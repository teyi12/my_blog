from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _
from .models import Adresse


DONATION_FORM_SESSION_KEY = "donation_checkout_form_data"

class AdresseForm(forms.ModelForm):
    class Meta:
        model = Adresse
        fields = ["rue", "ville", "code_postal", "pays", "telephone"]
        widgets = {
            "rue": forms.TextInput(attrs={"class": "form-control", "placeholder": "Rue et numéro"}),
            "ville": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ville"}),
            "code_postal": forms.TextInput(attrs={"class": "form-control", "placeholder": "Code postal"}),
            "pays": forms.TextInput(attrs={"class": "form-control", "placeholder": "Pays"}),
            "telephone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Téléphone"}),
        }

from django import forms
from .models import Adresse

class AdresseForm(forms.ModelForm):
    class Meta:
        model = Adresse
        fields = ["rue", "ville", "code_postal", "pays", "telephone"]


class DonationCheckoutForm(forms.Form):
    amount = forms.DecimalField(
        label=_("Montant (€)"),
        min_value=Decimal("1.00"),
        max_digits=10,
        decimal_places=2,
        initial=Decimal("5.00"),
        widget=forms.NumberInput(
            attrs={
                "id": "donation-amount",
                "inputmode": "decimal",
                "step": "0.01",
                "aria-describedby": "donation-amount-help",
            }
        ),
        error_messages={
            "required": _(
                "Saisissez un montant de don valide d’au moins 1 EUR, "
                "avec au maximum deux décimales."
            ),
            "invalid": _(
                "Saisissez un montant de don valide d’au moins 1 EUR, "
                "avec au maximum deux décimales."
            ),
            "min_value": _(
                "Saisissez un montant de don valide d’au moins 1 EUR, "
                "avec au maximum deux décimales."
            ),
            "max_digits": _(
                "Saisissez un montant de don valide d’au moins 1 EUR, "
                "avec au maximum deux décimales."
            ),
            "max_decimal_places": _(
                "Saisissez un montant de don valide d’au moins 1 EUR, "
                "avec au maximum deux décimales."
            ),
        },
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound and "amount" in self.errors:
            self.fields["amount"].widget.attrs.update(
                {
                    "aria-invalid": "true",
                    "aria-describedby": "donation-amount-help donation-amount-errors",
                }
            )
