from django import forms
from django.utils.text import slugify

from payments.models import Adresse

from .models import Categorie, Commande, FULFILLMENT_STATUS_CHOICES, Produit


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


class CommandeTraitementForm(forms.Form):
    statut = forms.ChoiceField(label="Nouveau statut")
    carrier = forms.CharField(
        label="Transporteur",
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Ex. DHL, Deutsche Post, UPS",
                "autocomplete": "off",
            }
        ),
    )
    tracking_number = forms.CharField(
        label="Numéro de suivi",
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Ex. 00340434161094000000",
                "autocomplete": "off",
            }
        ),
    )

    def __init__(self, *args, commande, **kwargs):
        super().__init__(*args, **kwargs)
        self.commande = commande
        labels = dict(FULFILLMENT_STATUS_CHOICES)
        allowed = commande.allowed_fulfillment_transitions()
        self.fields["statut"].choices = [
            (value, labels[value])
            for value, _label in FULFILLMENT_STATUS_CHOICES
            if value in allowed
        ]
        self.fields["statut"].widget.attrs.update({"class": "form-select"})

    def clean(self):
        cleaned_data = super().clean()
        statut = cleaned_data.get("statut")
        if statut == "SHIPPED":
            if not cleaned_data.get("carrier", "").strip():
                self.add_error("carrier", "Indiquez le transporteur avant de marquer la commande comme expédiée.")
            if not cleaned_data.get("tracking_number", "").strip():
                self.add_error("tracking_number", "Indiquez le numéro de suivi avant de marquer la commande comme expédiée.")
        return cleaned_data


class CommandeExpeditionForm(forms.ModelForm):
    class Meta:
        model = Commande
        fields = ["carrier", "tracking_number"]
        labels = {
            "carrier": "Transporteur",
            "tracking_number": "Numéro de suivi",
        }
        widgets = {
            "carrier": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex. DHL, Deutsche Post, UPS",
                    "autocomplete": "off",
                }
            ),
            "tracking_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex. TEST-71-2026",
                    "autocomplete": "off",
                }
            ),
        }

    def clean_carrier(self):
        carrier = self.cleaned_data["carrier"].strip()
        if not carrier:
            raise forms.ValidationError("Indiquez le transporteur.")
        return carrier

    def clean_tracking_number(self):
        tracking_number = self.cleaned_data["tracking_number"].strip()
        if not tracking_number:
            raise forms.ValidationError("Indiquez le numéro de suivi.")
        return tracking_number


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
