from modeltranslation.translator import TranslationOptions, register

from .models import Abonnement, Publicite


@register(Abonnement)
class AbonnementTranslationOptions(TranslationOptions):
    fields = ("nom", "description")
    required_languages = ("fr",)


@register(Publicite)
class PubliciteTranslationOptions(TranslationOptions):
    fields = ("titre",)
