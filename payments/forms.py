from django import forms
from .models import Adresse

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
