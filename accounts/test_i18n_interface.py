from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.utils import translation

from .forms import CustomUserCreationForm, CustomUserUpdateForm
from .models import CustomUser


class AccountsInterfaceI18nTests(TestCase):
    password = "Secure-account-password-2026"

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            email="ada@example.test",
            password=cls.password,
            first_name="Ada",
            last_name="Lovelace",
            photo="users/ada.webp",
            telephone="+49 30 123456",
            bio="Analytical engine pioneer",
        )

    def test_login_page_is_fully_localized(self):
        expectations = {
            "fr": (
                "/accounts/login/",
                "Connexion — Teyilawson",
                (
                    "Heureux de vous revoir.",
                    "Adresse e-mail",
                    "Mot de passe",
                    "Se connecter",
                ),
            ),
            "de": (
                "/de/accounts/login/",
                "Anmelden — Teyilawson",
                (
                    "Schön, dass Sie wieder da sind.",
                    "E-Mail-Adresse",
                    "Passwort",
                    "Anmelden",
                ),
            ),
            "en": (
                "/en/accounts/login/",
                "Sign in — Teyilawson",
                (
                    "Welcome back.",
                    "Email address",
                    "Password",
                    "Sign in",
                ),
            ),
        }

        for language, (url, title, expected_texts) in expectations.items():
            with self.subTest(language=language):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'<html lang="{language}">')
                self.assertContains(response, f"<title>{title}</title>")
                self.assertContains(response, 'name="csrfmiddlewaretoken"')
                for text in expected_texts:
                    self.assertContains(response, text)

                if language != "fr":
                    self.assertNotContains(response, "Heureux de vous revoir.")
                    self.assertNotContains(response, "Accéder à mon compte")
                    self.assertNotContains(response, "Pas encore de compte ?")

    def test_registration_page_and_lazy_form_labels_are_localized(self):
        expectations = {
            "fr": (
                "/accounts/register/",
                "Inscription — Teyilawson",
                "Rejoignez l’univers Teyilawson.",
                (
                    "Adresse e-mail",
                    "Mot de passe",
                    "Confirmation du mot de passe",
                    "Prénom",
                    "Nom",
                    "Photo de profil",
                    "Téléphone",
                    "Présentation",
                ),
                "Créer mon compte",
            ),
            "de": (
                "/de/accounts/register/",
                "Registrierung — Teyilawson",
                "Werden Sie Teil der Teyilawson-Community.",
                (
                    "E-Mail-Adresse",
                    "Passwort",
                    "Passwort bestätigen",
                    "Vorname",
                    "Nachname",
                    "Profilfoto",
                    "Telefon",
                    "Kurzprofil",
                ),
                "Mein Konto erstellen",
            ),
            "en": (
                "/en/accounts/register/",
                "Sign up — Teyilawson",
                "Join the Teyilawson community.",
                (
                    "Email address",
                    "Password",
                    "Password confirmation",
                    "First name",
                    "Last name",
                    "Profile photo",
                    "Phone",
                    "Bio",
                ),
                "Create my account",
            ),
        }

        for language, (url, title, heading, labels, button) in expectations.items():
            with self.subTest(language=language), translation.override(language):
                response = self.client.get(url)
                form = CustomUserCreationForm()

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f"<title>{title}</title>")
                self.assertContains(response, heading)
                self.assertContains(response, button)
                self.assertContains(response, 'name="csrfmiddlewaretoken"')
                for label in labels:
                    self.assertContains(response, label)
                self.assertEqual(str(form.fields["bio"].label), labels[-1])

                if language != "fr":
                    self.assertNotContains(response, "Rejoignez l’univers Teyilawson.")
                    self.assertNotContains(response, "Créer mon compte")
                    self.assertNotContains(response, "Déjà inscrit ?")

    def test_authenticated_profile_is_fully_localized(self):
        self.client.force_login(self.user)
        expectations = {
            "fr": (
                "/accounts/profile/",
                "Mon profil — Teyilawson",
                (
                    "Mon profil",
                    "Modifier mon profil",
                    "Prénom",
                    "Nom",
                    "Photo de profil",
                    "Téléphone",
                    "Présentation",
                ),
                "Photo de profil de ada@example.test",
            ),
            "de": (
                "/de/accounts/profile/",
                "Mein Profil — Teyilawson",
                (
                    "Mein Profil",
                    "Mein Profil bearbeiten",
                    "Vorname",
                    "Nachname",
                    "Profilfoto",
                    "Telefon",
                    "Kurzprofil",
                ),
                "Profilfoto von ada@example.test",
            ),
            "en": (
                "/en/accounts/profile/",
                "My profile — Teyilawson",
                (
                    "My profile",
                    "Edit my profile",
                    "First name",
                    "Last name",
                    "Profile photo",
                    "Phone",
                    "Bio",
                ),
                "Profile photo of ada@example.test",
            ),
        }

        for language, (url, title, expected_texts, photo_alt) in expectations.items():
            with self.subTest(language=language), translation.override(language):
                response = self.client.get(url)
                form = CustomUserUpdateForm(instance=self.user)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f"<title>{title}</title>")
                self.assertContains(response, self.user.email)
                self.assertContains(response, f'alt="{photo_alt}"')
                self.assertContains(response, 'enctype="multipart/form-data"')
                self.assertContains(response, 'name="csrfmiddlewaretoken"')
                for text in expected_texts:
                    self.assertContains(response, text)
                self.assertEqual(str(form.fields["bio"].label), expected_texts[-1])

                if language != "fr":
                    self.assertNotContains(
                        response,
                        "Mettez à jour les informations visibles dans votre espace personnel.",
                    )
                    self.assertNotContains(response, "Modifier mon profil")
                    self.assertNotContains(response, "Enregistrer les modifications")

    def test_invalid_login_and_registration_errors_follow_active_language(self):
        expectations = {
            "fr": ("/accounts/login/", "/accounts/register/", "Ce champ est obligatoire."),
            "de": (
                "/de/accounts/login/",
                "/de/accounts/register/",
                "Dieses Feld ist erforderlich.",
            ),
            "en": (
                "/en/accounts/login/",
                "/en/accounts/register/",
                "This field is required.",
            ),
        }

        for language, (login_url, register_url, error) in expectations.items():
            with self.subTest(language=language):
                login_response = self.client.post(login_url, {})
                register_response = self.client.post(register_url, {})

                self.assertEqual(login_response.status_code, 200)
                self.assertEqual(register_response.status_code, 200)
                self.assertContains(login_response, error)
                self.assertContains(register_response, error)

    def test_invalid_profile_photo_error_is_localized(self):
        self.client.force_login(self.user)
        expectations = {
            "fr": (
                "/accounts/profile/",
                "Le fichier sélectionné n’est pas une image valide.",
            ),
            "de": (
                "/de/accounts/profile/",
                "Die ausgewählte Datei ist kein gültiges Bild.",
            ),
            "en": (
                "/en/accounts/profile/",
                "The selected file is not a valid image.",
            ),
        }

        for language, (url, error) in expectations.items():
            with self.subTest(language=language):
                response = self.client.post(
                    url,
                    {
                        "first_name": self.user.first_name,
                        "last_name": self.user.last_name,
                        "telephone": self.user.telephone,
                        "bio": self.user.bio,
                        "photo": SimpleUploadedFile(
                            "invalid.png",
                            b"not-an-image",
                            content_type="image/png",
                        ),
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, error)

    def test_login_keeps_next_and_preserves_native_redirect_behavior(self):
        login_url = "/de/accounts/login/?next=/de/shop/"
        response = self.client.get(login_url)

        self.assertContains(response, 'name="next" value="/de/shop/"')

        invalid = self.client.post(
            login_url,
            {
                "username": self.user.email,
                "password": "incorrect",
                "next": "/de/shop/",
            },
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, 'name="next" value="/de/shop/"')

        valid = self.client.post(
            login_url,
            {
                "username": self.user.email,
                "password": self.password,
                "next": "/de/shop/",
            },
        )
        self.assertRedirects(valid, "/de/shop/", fetch_redirect_response=False)

    def test_registration_and_profile_update_behavior_is_unchanged(self):
        registration = self.client.post(
            "/accounts/register/",
            {
                "email": "new-user@example.test",
                "password1": self.password,
                "password2": self.password,
                "first_name": "Grace",
                "last_name": "Hopper",
                "telephone": "+1 555 0100",
                "bio": "Computer scientist",
            },
        )

        self.assertRedirects(registration, "/", fetch_redirect_response=False)
        registered_user = CustomUser.objects.get(email="new-user@example.test")
        self.assertEqual(int(self.client.session["_auth_user_id"]), registered_user.pk)

        profile_update = self.client.post(
            "/accounts/profile/",
            {
                "first_name": "Grace",
                "last_name": "Hopper",
                "telephone": "+1 555 0199",
                "bio": "Rear admiral and computer scientist",
            },
        )
        self.assertRedirects(
            profile_update,
            "/accounts/profile/",
            fetch_redirect_response=False,
        )
        registered_user.refresh_from_db()
        self.assertEqual(registered_user.telephone, "+1 555 0199")
        self.assertEqual(registered_user.bio, "Rear admiral and computer scientist")

    def test_profile_access_and_logout_security_are_unchanged(self):
        for language, profile_url, login_url in (
            ("fr", "/accounts/profile/", "/accounts/login/"),
            ("de", "/de/accounts/profile/", "/de/accounts/login/"),
            ("en", "/en/accounts/profile/", "/en/accounts/login/"),
        ):
            with self.subTest(language=language):
                response = self.client.get(profile_url)
                self.assertRedirects(
                    response,
                    f"{login_url}?next={profile_url}",
                    fetch_redirect_response=False,
                )

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        profile = csrf_client.get("/en/accounts/profile/")
        logout_url = "/en/accounts/logout/"
        token = csrf_client.cookies[settings.CSRF_COOKIE_NAME].value

        self.assertContains(profile, f'<form method="post" action="{logout_url}">')
        self.assertEqual(csrf_client.get(logout_url).status_code, 405)
        self.assertEqual(csrf_client.post(logout_url).status_code, 403)

        logout = csrf_client.post(
            logout_url,
            {"csrfmiddlewaretoken": token},
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertRedirects(logout, "/en/", fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", csrf_client.session)
