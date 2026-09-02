from django import forms
from .models import Produit


class ProduitForm(forms.ModelForm):
    class Meta:
        model = Produit
        fields = ["nom", "description", "prix", "image", "fichier"]


class AjouterAuPanierForm(forms.Form):
    quantite = forms.IntegerField(min_value=1, initial=1, label="Quantité")


from django import forms
from payments.models import Adresse

class AdresseForm(forms.ModelForm):
    class Meta:
        model = Adresse
        fields = ["rue", "ville", "code_postal", "pays", "telephone"]
        widgets = {
            "rue": forms.TextInput(attrs={"class": "form-control", "placeholder": "12 rue de Paris"}),
            "ville": forms.TextInput(attrs={"class": "form-control", "placeholder": "Paris"}),
            "code_postal": forms.TextInput(attrs={"class": "form-control", "placeholder": "75001"}),
            "pays": forms.TextInput(attrs={"class": "form-control", "placeholder": "France"}),
            "telephone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+33 6 12 34 56 78"}),
        }
