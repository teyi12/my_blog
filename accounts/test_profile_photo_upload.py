from io import BytesIO
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from cloudinary.exceptions import Error as CloudinaryError
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import translation
from PIL import Image, features

from accounts.forms import CustomUserCreationForm, CustomUserUpdateForm
from accounts.models import CustomUser
from blog.settings import get_media_storage_backend


def make_image_upload(image_format, filename, content_type):
    image_bytes = BytesIO()
    Image.new("RGB", (12, 12), color="navy").save(image_bytes, image_format)
    return SimpleUploadedFile(filename, image_bytes.getvalue(), content_type)


class ProfilePhotoConfigurationTests(SimpleTestCase):
    def test_production_media_storage_remains_cloudinary(self):
        self.assertEqual(
            get_media_storage_backend(True),
            "cloudinary_storage.storage.MediaCloudinaryStorage",
        )
        self.assertEqual(
            get_media_storage_backend(False),
            "django.core.files.storage.FileSystemStorage",
        )

    def test_photo_upload_limit_is_centralized_in_settings(self):
        self.assertEqual(settings.PROFILE_PHOTO_MAX_UPLOAD_SIZE, 5 * 1024 * 1024)

    def test_profile_template_keeps_multipart_encoding(self):
        template = (
            Path(settings.BASE_DIR)
            / "accounts"
            / "templates"
            / "accounts"
            / "profile.html"
        ).read_text(encoding="utf-8")

        self.assertIn('enctype="multipart/form-data"', template)

    def test_both_user_forms_share_the_restricted_photo_field(self):
        for form_class in (CustomUserCreationForm, CustomUserUpdateForm):
            field = form_class().fields["photo"]
            self.assertEqual(
                field.widget.attrs["accept"],
                "image/jpeg,image/png,image/webp",
            )


class ProfilePhotoUploadTests(TestCase):
    password = "A-secure-profile-password-2026"

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            email="profile-owner@example.com",
            password=cls.password,
            first_name="Ancien",
            last_name="Nom",
            telephone="12345",
            bio="Ancienne bio",
            photo="users/ancienne-photo.jpg",
        )
        cls.other_user = CustomUser.objects.create_user(
            email="other-profile@example.com",
            password=cls.password,
            first_name="Autre",
        )

    def setUp(self):
        self.profile_url = reverse("accounts:profile")
        self.photo_storage = CustomUser._meta.get_field("photo").storage

    def profile_data(self, **overrides):
        data = {
            "first_name": "Nouveau",
            "last_name": "Profil",
            "telephone": "67890",
            "bio": "Nouvelle bio",
        }
        data.update(overrides)
        return data

    def test_anonymous_get_redirects_to_login(self):
        response = self.client.get(self.profile_url)

        self.assertRedirects(
            response,
            f'{reverse("accounts:login")}?next={self.profile_url}',
            fetch_redirect_response=False,
        )

    def test_authenticated_get_works(self):
        self.client.force_login(self.user)

        response = self.client.get(self.profile_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'enctype="multipart/form-data"')

    def test_text_fields_can_be_updated_without_photo_storage(self):
        self.client.force_login(self.user)

        with patch.object(self.photo_storage, "save") as storage_save:
            response = self.client.post(self.profile_url, self.profile_data())

        self.assertRedirects(
            response, self.profile_url, fetch_redirect_response=False
        )
        storage_save.assert_not_called()
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Nouveau")
        self.assertEqual(self.user.last_name, "Profil")
        self.assertEqual(self.user.telephone, "67890")
        self.assertEqual(self.user.bio, "Nouvelle bio")
        self.assertEqual(self.user.photo.name, "users/ancienne-photo.jpg")

    def assert_valid_profile_upload(self, image_format, filename, content_type):
        self.client.force_login(self.user)
        upload = make_image_upload(image_format, filename, content_type)
        stored_name = f"users/stored-{filename.rsplit('.', 1)[0]}"

        with patch.object(
            self.photo_storage, "save", return_value=stored_name
        ) as storage_save:
            response = self.client.post(
                self.profile_url,
                self.profile_data(photo=upload),
            )

        self.assertRedirects(
            response, self.profile_url, fetch_redirect_response=False
        )
        storage_save.assert_called_once()
        self.user.refresh_from_db()
        self.assertEqual(self.user.photo.name, stored_name)

    def test_valid_jpeg_upload(self):
        self.assert_valid_profile_upload("JPEG", "portrait.jpg", "image/jpeg")

    def test_valid_png_upload(self):
        self.assert_valid_profile_upload("PNG", "portrait.png", "image/png")

    @skipUnless(features.check("webp"), "Pillow was built without WebP support")
    def test_valid_webp_upload_when_supported(self):
        self.assert_valid_profile_upload("WEBP", "portrait.webp", "image/webp")

    def test_fake_image_is_rejected_before_storage(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            "portrait.jpg",
            b"this is not an image",
            content_type="image/jpeg",
        )

        with patch.object(self.photo_storage, "save") as storage_save:
            response = self.client.post(
                self.profile_url,
                self.profile_data(photo=upload),
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Le fichier sélectionné n’est pas une image valide."
        )
        storage_save.assert_not_called()

    def test_disallowed_image_format_is_rejected_before_storage(self):
        self.client.force_login(self.user)
        upload = make_image_upload("GIF", "portrait.gif", "image/gif")

        with patch.object(self.photo_storage, "save") as storage_save:
            response = self.client.post(
                self.profile_url,
                self.profile_data(photo=upload),
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Format non pris en charge.")
        storage_save.assert_not_called()

    def test_oversized_image_is_rejected_before_storage(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            "portrait.png",
            b"0" * (settings.PROFILE_PHOTO_MAX_UPLOAD_SIZE + 1),
            content_type="image/png",
        )

        with patch.object(self.photo_storage, "save") as storage_save:
            response = self.client.post(
                self.profile_url,
                self.profile_data(photo=upload),
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "taille maximale autorisée de 5 Mo")
        storage_save.assert_not_called()

    def test_storage_error_returns_200_preserves_old_profile_and_hides_secrets(self):
        self.client.force_login(self.user)
        upload = make_image_upload("JPEG", "portrait.jpg", "image/jpeg")
        secret_marker = "CLOUDINARY_API_SECRET=must-not-appear"
        provider_message = "Provider rejected the supplied credentials"

        with self.assertLogs("accounts.views", level="ERROR") as captured_logs:
            with patch.object(
                self.photo_storage,
                "save",
                side_effect=CloudinaryError(
                    f"{provider_message}: {secret_marker}"
                ),
            ):
                response = self.client.post(
                    self.profile_url,
                    self.profile_data(photo=upload),
                )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "La photo n’a pas pu être enregistrée pour le moment.",
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.photo.name, "users/ancienne-photo.jpg")
        self.assertEqual(self.user.first_name, "Ancien")
        log_output = "\n".join(captured_logs.output)
        self.assertIn("exception_type=Error", log_output)
        self.assertIn("operation=profile_update", log_output)
        self.assertNotIn(secret_marker, log_output)
        self.assertNotIn(provider_message, log_output)

    def test_programming_and_database_errors_are_not_masked(self):
        self.client.force_login(self.user)

        for exception in (
            RuntimeError("programming error"),
            DatabaseError("database error"),
        ):
            with self.subTest(exception_type=type(exception).__name__):
                upload = make_image_upload("JPEG", "portrait.jpg", "image/jpeg")
                with patch.object(
                    self.photo_storage,
                    "save",
                    side_effect=exception,
                ):
                    with self.assertRaises(type(exception)):
                        self.client.post(
                            self.profile_url,
                            self.profile_data(photo=upload),
                        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.photo.name, "users/ancienne-photo.jpg")
        self.assertEqual(self.user.first_name, "Ancien")

    def test_storage_error_message_is_translated(self):
        self.client.force_login(self.user)
        upload = make_image_upload("PNG", "portrait.png", "image/png")

        with translation.override("en"):
            profile_url = reverse("accounts:profile")
            with patch.object(
                self.photo_storage,
                "save",
                side_effect=OSError("storage unavailable"),
            ):
                response = self.client.post(
                    profile_url,
                    self.profile_data(photo=upload),
                )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "The photo could not be saved right now. Please try again later.",
        )

    def test_user_cannot_modify_another_users_profile(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.profile_url,
            self.profile_data(
                id=self.other_user.pk,
                email=self.other_user.email,
            ),
        )

        self.assertRedirects(
            response, self.profile_url, fetch_redirect_response=False
        )
        self.user.refresh_from_db()
        self.other_user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Nouveau")
        self.assertEqual(self.other_user.first_name, "Autre")

    def test_existing_photo_can_still_be_cleared(self):
        self.client.force_login(self.user)

        with patch.object(self.photo_storage, "save") as storage_save:
            response = self.client.post(
                self.profile_url,
                self.profile_data(**{"photo-clear": "on"}),
            )

        self.assertRedirects(
            response, self.profile_url, fetch_redirect_response=False
        )
        storage_save.assert_not_called()
        self.user.refresh_from_db()
        self.assertFalse(self.user.photo)


class RegistrationPhotoUploadTests(TestCase):
    def test_registration_with_valid_photo_still_works(self):
        photo_storage = CustomUser._meta.get_field("photo").storage
        upload = make_image_upload("JPEG", "registration.jpg", "image/jpeg")

        with patch.object(
            photo_storage,
            "save",
            return_value="users/registered-photo",
        ) as storage_save:
            response = self.client.post(
                reverse("accounts:register"),
                {
                    "email": "new-user@example.com",
                    "password1": "A-secure-registration-password-2026",
                    "password2": "A-secure-registration-password-2026",
                    "first_name": "Nouvelle",
                    "last_name": "Personne",
                    "telephone": "123456",
                    "bio": "Présentation",
                    "photo": upload,
                },
            )

        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        storage_save.assert_called_once()
        user = CustomUser.objects.get(email="new-user@example.com")
        self.assertEqual(user.photo.name, "users/registered-photo")

    def test_registration_storage_error_is_controlled(self):
        photo_storage = CustomUser._meta.get_field("photo").storage
        upload = make_image_upload("PNG", "registration.png", "image/png")

        with patch.object(
            photo_storage,
            "save",
            side_effect=OSError("storage unavailable"),
        ):
            response = self.client.post(
                reverse("accounts:register"),
                {
                    "email": "failed-user@example.com",
                    "password1": "A-secure-registration-password-2026",
                    "password2": "A-secure-registration-password-2026",
                    "photo": upload,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "La photo n’a pas pu être enregistrée pour le moment.",
        )
        self.assertFalse(CustomUser.objects.filter(email="failed-user@example.com").exists())
