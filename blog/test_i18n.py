from django.conf import settings
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import translation


class I18nRoutingTests(TestCase):
    def test_i18n_settings_and_middleware_order(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fr")
        self.assertEqual(
            settings.LANGUAGES,
            [("fr", "Français"), ("de", "Deutsch"), ("en", "English")],
        )
        self.assertEqual(settings.LOCALE_PATHS, [settings.BASE_DIR / "locale"])
        self.assertLess(
            settings.MIDDLEWARE.index("django.contrib.sessions.middleware.SessionMiddleware"),
            settings.MIDDLEWARE.index("django.middleware.locale.LocaleMiddleware"),
        )
        self.assertLess(
            settings.MIDDLEWARE.index("django.middleware.locale.LocaleMiddleware"),
            settings.MIDDLEWARE.index("django.middleware.common.CommonMiddleware"),
        )

    def test_default_french_home_and_existing_routes_remain_unprefixed(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/articles/").status_code, 200)
        self.assertEqual(self.client.get("/shop/").status_code, 200)
        self.assertEqual(self.client.get("/accounts/login/").status_code, 200)

    def test_german_and_english_prefixes_activate_their_language(self):
        german = self.client.get("/de/")
        english = self.client.get("/en/")

        self.assertEqual(german.status_code, 200)
        self.assertEqual(german.wsgi_request.LANGUAGE_CODE, "de")
        self.assertContains(german, '<html lang="de">')
        self.assertEqual(english.status_code, 200)
        self.assertEqual(english.wsgi_request.LANGUAGE_CODE, "en")
        self.assertContains(english, '<html lang="en">')

    def test_public_routes_are_prefixed_when_reversed_in_german_and_english(self):
        with translation.override("de"):
            self.assertEqual(reverse("home"), "/de/")
            self.assertEqual(reverse("articles:articles"), "/de/articles/")
        with translation.override("en"):
            self.assertEqual(reverse("home"), "/en/")
            self.assertEqual(reverse("articles:articles"), "/en/articles/")

    def test_technical_payment_endpoints_remain_unprefixed(self):
        self.assertEqual(reverse("payments:stripe_webhook"), "/payments/webhook/")
        self.assertEqual(reverse("payments:cinetpay_ipn"), "/payments/cinetpay/ipn/")
        with translation.override("de"):
            self.assertEqual(reverse("payments:stripe_webhook"), "/payments/webhook/")
            self.assertEqual(reverse("payments:cinetpay_ipn"), "/payments/cinetpay/ipn/")

        self.assertEqual(self.client.post("/de/payments/webhook/").status_code, 404)
        self.assertEqual(self.client.post("/en/payments/webhook/").status_code, 404)

    def test_admin_remains_unprefixed(self):
        self.assertEqual(reverse("admin:index"), "/admin/")
        self.assertEqual(self.client.get("/de/admin/").status_code, 404)


class LanguageSelectorTests(TestCase):
    def setUp(self):
        self.csrf_client = Client(enforce_csrf_checks=True)
        self.set_language_url = reverse("set_language")

    def _csrf_token(self, url="/"):
        response = self.csrf_client.get(url)
        self.assertEqual(response.status_code, 200)
        return self.csrf_client.cookies["csrftoken"].value

    def test_selector_is_a_csrf_protected_post_form(self):
        response = self.client.get("/articles/")

        self.assertContains(response, f'action="{self.set_language_url}"')
        self.assertContains(response, 'method="post"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'name="next" value="/articles/"')
        self.assertContains(response, 'id="language-select"')

    def test_language_change_requires_post_and_csrf(self):
        self.assertEqual(
            self.csrf_client.get(self.set_language_url, {"language": "de"}).status_code,
            405,
        )
        self.assertEqual(
            self.csrf_client.post(
                self.set_language_url,
                {"language": "de", "next": "/"},
            ).status_code,
            403,
        )

    def test_language_change_translates_internal_next_url(self):
        token = self._csrf_token("/articles/")

        response = self.csrf_client.post(
            self.set_language_url,
            {"language": "de", "next": "/articles/"},
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertRedirects(response, "/de/articles/", fetch_redirect_response=False)
        self.assertEqual(response.cookies[settings.LANGUAGE_COOKIE_NAME].value, "de")

    def test_external_next_is_rejected_with_a_safe_home_fallback(self):
        token = self._csrf_token()

        response = self.csrf_client.post(
            self.set_language_url,
            {"language": "en", "next": "https://example.org/collect"},
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(response["Location"].startswith("https://example.org"))
        self.assertEqual(response["Location"], "/en/")
