from modeltranslation.translator import TranslationOptions, register

from .models import Article, CategorieArticle


@register(CategorieArticle)
class CategorieArticleTranslationOptions(TranslationOptions):
    fields = ("nom",)
    required_languages = ("fr",)


@register(Article)
class ArticleTranslationOptions(TranslationOptions):
    fields = ("titre", "contenu", "image_alt")
