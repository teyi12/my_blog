from urllib.parse import urlsplit

from django.conf import settings
from django.utils import translation
from django.utils.translation import get_language_from_path
from django.views.decorators.http import require_POST
from django.views.i18n import set_language as django_set_language


@require_POST
def set_language(request):
    """Expose Django's language switcher as a CSRF-protected POST endpoint."""
    next_url = request.POST.get("next", request.GET.get("next", "")) or ""
    try:
        source_path = urlsplit(next_url).path
    except ValueError:
        source_path = ""
    source_language = get_language_from_path(source_path) or settings.LANGUAGE_CODE

    with translation.override(source_language):
        return django_set_language(request)
