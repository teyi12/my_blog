from modeltranslation.translator import TranslationOptions, register

from .models import Video


@register(Video)
class VideoTranslationOptions(TranslationOptions):
    fields = ("titre", "description", "miniature_alt")
    required_languages = {"fr": ("titre", "description")}
