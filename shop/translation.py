from modeltranslation.translator import TranslationOptions, register

from .models import Categorie, Produit


@register(Categorie)
class CategorieTranslationOptions(TranslationOptions):
    fields = ("nom",)


@register(Produit)
class ProduitTranslationOptions(TranslationOptions):
    fields = ("nom", "description")
