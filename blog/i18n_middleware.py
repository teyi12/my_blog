from django.conf import settings
from django.utils import translation


class PaymentLanguageCookieMiddleware:
    """Honor the selected language on the intentionally unprefixed payment URLs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info.startswith("/payments/"):
            language_code = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
            supported_languages = {code for code, _name in settings.LANGUAGES}
            if language_code in supported_languages:
                with translation.override(language_code):
                    request.LANGUAGE_CODE = language_code
                    return self.get_response(request)
        return self.get_response(request)
