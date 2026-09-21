from modeltranslation.translator import TranslationOptions, register

from .models import Categorie, Produit, ProduitImage


@register(Categorie)
class CategorieTranslationOptions(TranslationOptions):
    fields = ("nom",)


@register(Produit)
class ProduitTranslationOptions(TranslationOptions):
    fields = ("nom", "description")


@register(ProduitImage)
class ProduitImageTranslationOptions(TranslationOptions):
    fields = ("texte_alternatif",)
