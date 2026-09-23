from pathlib import Path

from django.conf import settings
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import translation

from accounts.models import CustomUser


class AccountsPremiumUITests(TestCase):
    password = "A-secure-account-password-2026"

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            email="premium-ui@example.test",
            password=cls.password,
            first_name="Ada",
            last_name="Lovelace",
            telephone="+49 30 123456",
            bio="Analytical engine pioneer",
        )

    def test_existing_pages_have_one_h1_and_semantic_forms(self):
        for url in (reverse("accounts:login"), reverse("accounts:register")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content.count(b"<h1"), 1)
                self.assertContains(response, "<form")
                self.assertContains(response, 'data-account-form')
                self.assertContains(response, 'name="csrfmiddlewaretoken"')

        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.count(b"<h1"), 1)
        self.assertContains(response, "<fieldset")
        self.assertContains(response, 'enctype="multipart/form-data"')

    def test_fields_expose_labels_autocomplete_required_and_error_metadata(self):
        response = self.client.post(reverse("accounts:register"), {})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'autocomplete="email"')
        self.assertContains(response, 'autocomplete="new-password"', count=2)
        self.assertContains(response, 'for="id_email"')
        self.assertContains(response, "(obligatoire)")
        self.assertContains(response, 'id="id_email"')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, 'aria-describedby="id_email_error"')
        self.assertContains(response, 'id="id_email_error"')
        self.assertContains(response, 'data-account-error-summary')
        self.assertContains(response, 'href="#id_email"')

    def test_login_password_is_progressive_and_never_repopulated(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": self.user.email,
                "password": "password-that-must-not-be-rendered",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "password-that-must-not-be-rendered")
        self.assertContains(response, 'autocomplete="current-password"')
        self.assertContains(response, 'data-password-toggle')
        self.assertContains(response, 'aria-pressed="false"')
        self.assertContains(response, "Afficher le mot de passe")
        self.assertContains(response, 'src="/static/js/accounts.js" defer')

    def test_registration_password_values_are_not_rendered_after_error(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "email": "new-account@example.test",
                "password1": "Secret-value-not-for-html-2026",
                "password2": "different-value",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Secret-value-not-for-html-2026")
        self.assertNotContains(response, "different-value")

    def test_login_accepts_internal_next_and_rejects_external_next(self):
        internal = self.client.post(
            reverse("accounts:login"),
            {
                "username": self.user.email,
                "password": self.password,
                "next": "/shop/",
            },
        )
        self.assertRedirects(internal, "/shop/", fetch_redirect_response=False)

        self.client.logout()
        external = self.client.post(
            reverse("accounts:login"),
            {
                "username": self.user.email,
                "password": self.password,
                "next": "https://attacker.example/collect",
            },
        )
        self.assertRedirects(external, "/", fetch_redirect_response=False)

        self.client.logout()
        scheme_relative = self.client.post(
            reverse("accounts:login"),
            {
                "username": self.user.email,
                "password": self.password,
                "next": "//attacker.example/collect",
            },
        )
        self.assertRedirects(scheme_relative, "/", fetch_redirect_response=False)

    def test_csrf_and_http_method_guards_remain_active(self):
        csrf_client = Client(enforce_csrf_checks=True)
        self.assertEqual(
            csrf_client.post(reverse("accounts:login"), {}).status_code,
            403,
        )
        self.assertEqual(
            csrf_client.post(reverse("accounts:register"), {}).status_code,
            403,
        )
        csrf_client.force_login(self.user)
        self.assertEqual(
            csrf_client.post(reverse("accounts:profile"), {}).status_code,
            403,
        )
        self.assertEqual(
            csrf_client.get(reverse("accounts:logout")).status_code,
            405,
        )

    def test_profile_values_are_escaped_and_photo_fallback_is_localized(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "Aucune photo de profil")

        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "<script>alert(1)</script>",
                "last_name": "Lovelace",
                "telephone": "123456789012345678901",
                "bio": "<img src=x onerror=alert(1)>",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertNotContains(response, "<img src=x onerror=alert(1)>")

    def test_photo_controls_keep_server_upload_and_local_preview_markup(self):
        response = self.client.get(reverse("accounts:register"))

        self.assertContains(response, 'enctype="multipart/form-data"')
        self.assertContains(
            response,
            'accept="image/jpeg,image/png,image/webp"',
        )
        self.assertContains(response, 'data-photo-preview')
        self.assertContains(response, 'data-photo-preview-cancel')
        self.assertContains(response, 'width="160"')
        self.assertContains(response, 'height="160"')

    def test_new_interface_copy_is_translated_in_german_and_english(self):
        expectations = {
            "de": {
                "login": ("Ihr persönlicher Bereich", "Passwort anzeigen"),
                "register": ("Zugangsdaten", "Persönliche Angaben"),
                "profile": (
                    "Ihre E-Mail-Adresse bleibt die Anmeldekennung",
                    "Foto und Kurzprofil",
                ),
            },
            "en": {
                "login": ("Your personal area", "Show password"),
                "register": ("Sign-in details", "Personal information"),
                "profile": (
                    "Your email address remains the identifier",
                    "Photo and bio",
                ),
            },
        }

        for language, pages in expectations.items():
            with self.subTest(language=language), translation.override(language):
                login = self.client.get(f"/{language}/accounts/login/")
                register = self.client.get(f"/{language}/accounts/register/")
                self.client.force_login(self.user)
                profile = self.client.get(f"/{language}/accounts/profile/")

                for response, expected_texts in (
                    (login, pages["login"]),
                    (register, pages["register"]),
                    (profile, pages["profile"]),
                ):
                    self.assertEqual(response.status_code, 200)
                    for text in expected_texts:
                        self.assertContains(response, text)

    def test_password_validators_and_authentication_routes_are_unchanged(self):
        self.assertEqual(
            [item["NAME"] for item in settings.AUTH_PASSWORD_VALIDATORS],
            [
                "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
                "django.contrib.auth.password_validation.MinimumLengthValidator",
                "django.contrib.auth.password_validation.CommonPasswordValidator",
                "django.contrib.auth.password_validation.NumericPasswordValidator",
            ],
        )
        self.assertEqual(reverse("accounts:login"), "/accounts/login/")
        self.assertEqual(reverse("accounts:register"), "/accounts/register/")
        self.assertEqual(reverse("accounts:profile"), "/accounts/profile/")
        self.assertEqual(reverse("accounts:logout"), "/accounts/logout/")

    def test_account_assets_stay_scoped_and_use_shared_tokens(self):
        base_dir = Path(settings.BASE_DIR)
        account_css = (base_dir / "static/css/accounts.css").read_text(
            encoding="utf-8"
        )
        templates = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (base_dir / "accounts/templates/accounts").glob("*.html")
        )

        self.assertNotIn("!important", account_css)
        self.assertNotIn("|safe", templates)
        self.assertIn("@media (max-width: 61.99rem)", account_css)
        self.assertIn("@media (max-width: 47.99rem)", account_css)
        self.assertIn("@media (max-width: 24.99rem)", account_css)
