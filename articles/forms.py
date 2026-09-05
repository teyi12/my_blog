from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Article


class ArticleForm(forms.ModelForm):
    class Meta:
        model = Article
        fields = [
            "titre_fr",
            "titre_de",
            "titre_en",
            "contenu_fr",
            "contenu_de",
            "contenu_en",
            "image",
            "sponsor",
            "est_sponsorise",
            "is_premium",
        ]
        labels = {
            "titre_fr": _("Titre [fr]"),
            "titre_de": _("Titre [de]"),
            "titre_en": _("Titre [en]"),
            "contenu_fr": _("Contenu [fr]"),
            "contenu_de": _("Contenu [de]"),
            "contenu_en": _("Contenu [en]"),
            "image": _("Image principale"),
            "sponsor": _("Sponsor"),
            "est_sponsorise": _("Article sponsorisé"),
            "is_premium": _("Contenu premium"),
        }
        help_texts = {
            "titre_de": _(
                "Facultatif : le titre français sera utilisé en allemand si ce champ est vide."
            ),
            "titre_en": _(
                "Facultatif : le titre français sera utilisé en anglais si ce champ est vide."
            ),
            "contenu_de": _(
                "Facultatif : le contenu français sera utilisé en allemand si ce champ est vide."
            ),
            "contenu_en": _(
                "Facultatif : le contenu français sera utilisé en anglais si ce champ est vide."
            ),
        }
        error_messages = {
            "titre_fr": {"required": _("Le titre français est obligatoire.")},
            "contenu_fr": {"required": _("Le contenu français est obligatoire.")},
        }
        widgets = {
            "titre_fr": forms.TextInput(attrs={"class": "form-control"}),
            "titre_de": forms.TextInput(attrs={"class": "form-control"}),
            "titre_en": forms.TextInput(attrs={"class": "form-control"}),
            "contenu_fr": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
            "contenu_de": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
            "contenu_en": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
            "sponsor": forms.TextInput(attrs={"class": "form-control"}),
            "image": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "est_sponsorise": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "is_premium": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["titre_fr"].required = True
        self.fields["contenu_fr"].required = True
        for field_name in ("titre_de", "titre_en", "contenu_de", "contenu_en"):
            self.fields[field_name].required = False
