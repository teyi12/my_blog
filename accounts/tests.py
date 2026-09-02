from io import StringIO
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase

from accounts.models import CustomUser


class CreateSuperuserCommandTests(TestCase):
    required_variables = {
        "DJANGO_SUPERUSER_EMAIL": "render-admin@example.com",
        "DJANGO_SUPERUSER_PASSWORD": "environment-only-password",
    }

    def test_missing_required_environment_variables_fails_cleanly(self):
        with patch.dict(
            "os.environ",
            {"DJANGO_SUPERUSER_EMAIL": "", "DJANGO_SUPERUSER_PASSWORD": ""},
        ):
            with self.assertRaisesMessage(CommandError, "sont obligatoires"):
                call_command("create_superuser")

        self.assertFalse(CustomUser.objects.exists())

    def test_creates_superuser_without_logging_password(self):
        output = StringIO()
        with patch.dict("os.environ", self.required_variables):
            call_command("create_superuser", stdout=output)

        user = CustomUser.objects.get(email="render-admin@example.com")
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.check_password("environment-only-password"))
        self.assertNotIn("environment-only-password", output.getvalue())

    def test_existing_superuser_password_is_never_overwritten(self):
        user = CustomUser.objects.create_superuser(
            email="render-admin@example.com",
            password="original-password",
        )
        output = StringIO()
        variables = {
            **self.required_variables,
            "DJANGO_SUPERUSER_PASSWORD": "replacement-password",
        }

        with patch.dict("os.environ", variables):
            call_command("create_superuser", stdout=output)

        user.refresh_from_db()
        self.assertTrue(user.check_password("original-password"))
        self.assertFalse(user.check_password("replacement-password"))
        self.assertNotIn("replacement-password", output.getvalue())
