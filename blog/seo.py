from html import unescape
from urllib.parse import urlsplit, urlunsplit

from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.urls import reverse
from django.utils import translation
from django.utils.html import strip_tags
from django.utils.text import Truncator
from django.utils.translation import gettext_lazy as _


SEO_LANGUAGES = ("fr", "de", "en")
OG_LOCALES = {"fr": "fr_FR", "de": "de_DE", "en": "en_US"}
SOCIAL_FALLBACK_IMAGE = "images/home-hero.jpg"
SOCIAL_FALLBACK_BACKUP = "images/home-hero-fallback.svg"
PRODUCT_CATEGORY_DESCRIPTION = _(
    "Découvrez les produits disponibles dans cette sélection."
)

STATIC_PAGE_METADATA = {
    "home": (
        _("Teyilawson — Articles, découvertes et boutique"),
        _(
            "Retrouvez des articles inspirants, des expériences à découvrir et "
            "une boutique sélectionnée pour aller à l’essentiel."
        ),
    ),
    "about": (
        _("À propos — Teyilawson"),
        _(
            "Teyilawson réunit contenus éditoriaux, découvertes et sélection de "
            "produits dans une expérience simple, utile et soigneusement construite."
        ),
    ),
    "contact": (
        _("Contact — Teyilawson"),
        _(
            "Une question, une proposition de partenariat ou simplement un message ? "
            "Écrivez-nous directement via ce formulaire."
        ),
    ),
    "articles:articles": (
        _("Articles — Teyilawson"),
        _(
            "Récits, expériences et réflexions réunis dans un espace éditorial clair, "
            "pensé pour prendre le temps de découvrir et de comprendre."
        ),
    ),
    "shop:liste": (
        _("Boutique — Teyilawson"),
        _(
            "Découvrez une sélection claire et soignée de produits, avec une "
            "expérience d’achat simple du choix au paiement."
        ),
    ),
    "videos:list": (
        _("Vidéos et vlogs — Teyilawson"),
        _(
            "Reportages, expériences et perspectives réunis dans un espace vidéo "
            "clair et immersif."
        ),
    ),
    "monetization:abonnements": (
        _("Abonnements Premium — Teyilawson"),
        _(
            "Les offres ci-dessous décrivent les formules disponibles. L’activation "
            "automatique n’est réalisée qu’après confirmation d’un paiement sécurisé."
        ),
    ),
    "monetization:partenariat": (
        _("Partenariat — Teyilawson"),
        _(
            "Présentez votre projet, votre entreprise et le type de collaboration "
            "envisagé. Chaque demande est examinée avant toute mise en avant."
        ),
    ),
    "monetization:affiliation": (
        _("Affiliation — Teyilawson"),
        _(
            "L’affiliation doit rester utile au lecteur. Présentez la plateforme, le "
            "produit concerné et le contexte dans lequel vous imaginez la collaboration."
        ),
    ),
    "monetization:publicites": (
        _("Publicités — Teyilawson"),
        _(
            "Les contenus commerciaux sont présentés comme tels afin de préserver une "
            "lecture claire et transparente."
        ),
    ),
}


def clean_description(value, length=160):
    """Return plain, compact text suitable for a metadata attribute."""
    plain_text = unescape(strip_tags(str(value or "")))
    compact_text = " ".join(plain_text.split())
    return Truncator(compact_text).chars(length)


def translated_value(instance, field_name, language_code):
    """Read an explicit translation column without modeltranslation fallback."""
    return getattr(instance, f"{field_name}_{language_code}", None)


def available_translation_languages(instance, required_fields):
    """Return FR plus DE/EN only when every required explicit column is populated."""
    languages = ["fr"]
    for language_code in SEO_LANGUAGES[1:]:
        if all(
            str(translated_value(instance, field, language_code) or "").strip()
            for field in required_fields
        ):
            languages.append(language_code)
    return tuple(languages)


def localized_path(view_name, language_code, kwargs=None):
    with translation.override(language_code):
        return reverse(view_name, kwargs=kwargs)


def absolute_url(request, path, force_https=False):
    url = request.build_absolute_uri(path)
    if not force_https:
        return url
    parsed = urlsplit(url)
    return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def social_image_url(request, image=None):
    image_url = ""
    if image and getattr(image, "name", "") != "default.jpg":
        try:
            image_url = image.url
        except (AttributeError, ValueError):
            image_url = ""
    if not image_url:
        fallback = (
            SOCIAL_FALLBACK_IMAGE
            if finders.find(SOCIAL_FALLBACK_IMAGE)
            else SOCIAL_FALLBACK_BACKUP
        )
        image_url = static(fallback)
    return absolute_url(request, image_url, force_https=True)


def _metadata(
    request,
    *,
    title,
    description,
    canonical,
    robots,
    languages=(),
    view_name=None,
    kwargs=None,
    image=None,
    og_type="website",
    effective_language=None,
):
    active_language = translation.get_language() or "fr"
    effective_language = effective_language or active_language
    alternates = (
        [
            {
                "language": language_code,
                "url": absolute_url(
                    request,
                    localized_path(view_name, language_code, kwargs),
                ),
            }
            for language_code in languages
        ]
        if view_name
        else []
    )
    alternate_locales = [
        OG_LOCALES[language_code]
        for language_code in languages
        if language_code != effective_language
    ]
    return {
        "title": str(title),
        "description": clean_description(description),
        "robots": robots,
        "canonical": canonical,
        "alternates": alternates,
        "x_default": next(
            (item["url"] for item in alternates if item["language"] == "fr"),
            "",
        ),
        "og_type": og_type,
        "og_image": social_image_url(request, image),
        "og_locale": OG_LOCALES.get(effective_language, OG_LOCALES["fr"]),
        "og_locale_alternates": alternate_locales,
        "site_name": "Teyilawson",
        "twitter_card": "summary_large_image",
    }


def build_default_seo(request):
    return _metadata(
        request,
        title="Teyilawson",
        description=STATIC_PAGE_METADATA["home"][1],
        canonical=absolute_url(request, request.path),
        robots="noindex,follow",
    )


def build_static_seo(request, view_name):
    title, description = STATIC_PAGE_METADATA[view_name]
    active_language = translation.get_language() or "fr"
    canonical = absolute_url(
        request,
        localized_path(view_name, active_language),
    )
    return _metadata(
        request,
        title=title,
        description=description,
        canonical=canonical,
        robots="index,follow",
        languages=SEO_LANGUAGES,
        view_name=view_name,
        effective_language=active_language,
    )


def build_dynamic_seo(
    request,
    *,
    instance,
    view_name,
    kwargs,
    title_field,
    required_fields,
    description_field=None,
    default_description=None,
    image_field=None,
    og_type="website",
):
    active_language = translation.get_language() or "fr"
    languages = available_translation_languages(instance, required_fields)
    is_real_translation = active_language in languages
    effective_language = active_language if is_real_translation else "fr"
    title = (
        translated_value(instance, title_field, effective_language)
        or translated_value(instance, title_field, "fr")
        or getattr(instance, title_field)
    )
    if description_field:
        description = (
            translated_value(instance, description_field, effective_language)
            or translated_value(instance, description_field, "fr")
            or getattr(instance, description_field)
            or title
        )
    else:
        with translation.override(effective_language):
            description = str(default_description or title)
    canonical_language = active_language if is_real_translation else "fr"
    canonical = absolute_url(
        request,
        localized_path(view_name, canonical_language, kwargs),
    )
    image = getattr(instance, image_field, None) if image_field else None
    return _metadata(
        request,
        title=f"{title} — Teyilawson",
        description=description,
        canonical=canonical,
        robots="index,follow" if is_real_translation else "noindex,follow",
        languages=languages,
        view_name=view_name,
        kwargs=kwargs,
        image=image,
        og_type=og_type,
        effective_language=effective_language,
    )
