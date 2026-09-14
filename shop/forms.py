import uuid

from django import forms
from django.db.models import Q
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from payments.models import Adresse

from .fulfillment import allowed_order_fulfillment_transitions
from .models import Categorie, Commande, FULFILLMENT_STATUS_CHOICES, Produit


class ProduitForm(forms.ModelForm):
    class Meta:
        model = Produit
        fields = [
            "nom",
            "description",
            "prix",
            "low_stock_threshold",
            "image",
            "fichier",
        ]


class StockAdjustmentForm(forms.Form):
    produit = forms.ModelChoiceField(
        queryset=Produit.objects.none(),
        label=_("Produit"),
    )
    quantity = forms.IntegerField(label=_("Variation de stock"))
    reason = forms.CharField(
        label=_("Motif"),
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    idempotency_key = forms.UUIDField(
        initial=uuid.uuid4,
        widget=forms.HiddenInput,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produit"].queryset = (
            Produit.objects.filter(stock__isnull=False)
            .filter(Q(fichier="") | Q(fichier__isnull=True))
            .order_by("nom", "pk")
        )
        for field_name in ("produit", "quantity", "reason"):
            self.fields[field_name].widget.attrs.setdefault("class", "form-control")

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity == 0:
            raise forms.ValidationError(_("La variation doit être différente de zéro."))
        return quantity

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise forms.ValidationError(_("Le motif est obligatoire."))
        return reason


class CategorieForm(forms.ModelForm):
    class Meta:
        model = Categorie
        fields = ["nom"]
        labels = {"nom": _("Nom de la catégorie")}
        widgets = {
            "nom": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("Ex. Mode, Livres, Accessoires"),
                    "autocomplete": "off",
                }
            )
        }

    def clean_nom(self):
        nom = self.cleaned_data["nom"].strip()
        duplicate_name = Categorie.objects.filter(nom__iexact=nom).exclude(pk=self.instance.pk)
        if duplicate_name.exists():
            raise forms.ValidationError(_("Une catégorie portant ce nom existe déjà."))

        candidate_slug = slugify(nom)
        duplicate_slug = Categorie.objects.filter(slug=candidate_slug).exclude(pk=self.instance.pk)
        if duplicate_slug.exists():
            raise forms.ValidationError(
                _("Ce nom produit un identifiant déjà utilisé par une autre catégorie.")
            )
        return nom

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.slug = slugify(instance.nom)
        if commit:
            instance.save()
        return instance


REQUIRED_ERROR = _("Ce champ est obligatoire.")


class CommandeTraitementForm(forms.Form):
    statut = forms.ChoiceField(label=_("Nouveau statut"))
    carrier = forms.CharField(
        label=_("Transporteur"),
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": _("Ex. DHL, Deutsche Post, UPS"),
                "autocomplete": "off",
            }
        ),
    )
    tracking_number = forms.CharField(
        label=_("Numéro de suivi"),
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": _("Ex. 00340434161094000000"),
                "autocomplete": "off",
            }
        ),
    )
    note = forms.CharField(
        label=_("Note opérationnelle"),
        max_length=1000,
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": _("Information interne facultative"),
            }
        ),
    )
    idempotency_key = forms.UUIDField(
        required=False,
        initial=uuid.uuid4,
        widget=forms.HiddenInput,
    )

    def __init__(self, *args, commande, **kwargs):
        super().__init__(*args, **kwargs)
        self.commande = commande
        labels = dict(FULFILLMENT_STATUS_CHOICES)
        allowed = allowed_order_fulfillment_transitions(commande)
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
                self.add_error("carrier", _("Indiquez le transporteur avant de marquer la commande comme expédiée."))
            if not cleaned_data.get("tracking_number", "").strip():
                self.add_error("tracking_number", _("Indiquez le numéro de suivi avant de marquer la commande comme expédiée."))
        return cleaned_data


class CommandeExpeditionForm(forms.ModelForm):
    note = forms.CharField(
        label=_("Note opérationnelle"),
        max_length=1000,
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": _("Motif de la mise à jour du suivi"),
            }
        ),
    )
    idempotency_key = forms.UUIDField(
        required=False,
        initial=uuid.uuid4,
        widget=forms.HiddenInput,
    )

    class Meta:
        model = Commande
        fields = ["carrier", "tracking_number"]
        labels = {
            "carrier": _("Transporteur"),
            "tracking_number": _("Numéro de suivi"),
        }
        widgets = {
            "carrier": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("Ex. DHL, Deutsche Post, UPS"),
                    "autocomplete": "off",
                }
            ),
            "tracking_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("Ex. TEST-71-2026"),
                    "autocomplete": "off",
                }
            ),
        }

    def clean_carrier(self):
        carrier = self.cleaned_data["carrier"].strip()
        if not carrier:
            raise forms.ValidationError(_("Indiquez le transporteur."))
        return carrier

    def clean_tracking_number(self):
        tracking_number = self.cleaned_data["tracking_number"].strip()
        if not tracking_number:
            raise forms.ValidationError(_("Indiquez le numéro de suivi."))
        return tracking_number


class AjouterAuPanierForm(forms.Form):
    quantite = forms.IntegerField(min_value=1, initial=1, label=_("Quantité"))


class AdresseForm(forms.ModelForm):
    class Meta:
        model = Adresse
        fields = ["rue", "ville", "code_postal", "pays", "telephone"]
        labels = {
            "rue": _("Rue"),
            "ville": _("Ville"),
            "code_postal": _("Code postal"),
            "pays": _("Pays"),
            "telephone": _("Téléphone"),
        }
        error_messages = {
            "rue": {"required": REQUIRED_ERROR},
            "ville": {"required": REQUIRED_ERROR},
            "code_postal": {"required": REQUIRED_ERROR},
            "pays": {"required": REQUIRED_ERROR},
        }
        widgets = {
            "rue": forms.TextInput(attrs={"class": "form-control", "placeholder": _("12 rue de Paris")}),
            "ville": forms.TextInput(attrs={"class": "form-control", "placeholder": _("Paris")}),
            "code_postal": forms.TextInput(attrs={"class": "form-control", "placeholder": "75001"}),
            "pays": forms.TextInput(attrs={"class": "form-control", "placeholder": _("France")}),
            "telephone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+33 6 12 34 56 78"}),
        }
