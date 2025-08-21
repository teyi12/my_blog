from django import forms
from .models import DemandePartenariat, DemandeAffiliation

class PartenariatForm(forms.ModelForm):
    class Meta:
        model = DemandePartenariat
        fields = ["nom", "email", "entreprise", "message"]


class AffiliationForm(forms.ModelForm):
    class Meta:
        model = DemandeAffiliation
        fields = ["nom", "email", "plateforme", "produit", "message"]
