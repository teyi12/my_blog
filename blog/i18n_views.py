from django.views.decorators.http import require_POST
from django.views.i18n import set_language as django_set_language


@require_POST
def set_language(request):
    """Expose Django's language switcher as a CSRF-protected POST endpoint."""
    return django_set_language(request)
