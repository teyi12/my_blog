from modeltranslation.translator import TranslationOptions, register

from .models import Abonnement, Publicite


@register(Abonnement)
class AbonnementTranslationOptions(TranslationOptions):
    fields = ("nom", "description")


@register(Publicite)
class PubliciteTranslationOptions(TranslationOptions):
    fields = ("titre",)
