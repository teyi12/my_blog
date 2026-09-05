from modeltranslation.translator import TranslationOptions, register

from .models import Article


@register(Article)
class ArticleTranslationOptions(TranslationOptions):
    fields = ("titre", "contenu")
