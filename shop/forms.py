from django import forms
from django.utils.text import slugify

from payments.models import Adresse

from .models import Categorie, Produit


class ProduitForm(forms.ModelForm):
    class Meta:
        model = Produit
        fields = ["nom", "description", "prix", "image", "fichier"]


class CategorieForm(forms.ModelForm):
    class Meta:
        model = Categorie
        fields = ["nom"]
        labels = {"nom": "Nom de la catégorie"}
        widgets = {
            "nom": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex. Mode, Livres, Accessoires",
                    "autocomplete": "off",
                }
            )
        }

    def clean_nom(self):
        nom = self.cleaned_data["nom"].strip()
        duplicate_name = Categorie.objects.filter(nom__iexact=nom).exclude(pk=self.instance.pk)
        if duplicate_name.exists():
            raise forms.ValidationError("Une catégorie portant ce nom existe déjà.")

        candidate_slug = slugify(nom)
        duplicate_slug = Categorie.objects.filter(slug=candidate_slug).exclude(pk=self.instance.pk)
        if duplicate_slug.exists():
            raise forms.ValidationError("Ce nom produit un identifiant déjà utilisé par une autre catégorie.")
        return nom

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.slug = slugify(instance.nom)
        if commit:
            instance.save()
        return instance


class AjouterAuPanierForm(forms.Form):
    quantite = forms.IntegerField(min_value=1, initial=1, label="Quantité")


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
