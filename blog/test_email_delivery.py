import os
from smtplib import SMTPException
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.smtp import EmailBackend
from django.test import SimpleTestCase, TestCase, override_settings

from blog.settings import env_positive_int, validate_email_transport_security


CONTACT_URL = "/contact/"
CONTACT_DATA = {
    "prenom": "Ada",
    "nom": "Lovelace",
    "email": "ada@example.test",
    "message": "Contenu confidentiel du formulaire",
}


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CONTACT_EMAIL="contact@example.test",
    DEFAULT_FROM_EMAIL="noreply@example.test",
    EMAIL_HOST_USER="smtp-login@example.test",
)
class ContactEmailDeliveryTests(TestCase):
    def test_contact_email_is_the_only_recipient(self):
        response = self.client.post(CONTACT_URL, CONTACT_DATA)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["contact@example.test"])
        self.assertNotIn(settings.EMAIL_HOST_USER, mail.outbox[0].to)

    def test_success_redirects_and_displays_confirmation(self):
        response = self.client.post(CONTACT_URL, CONTACT_DATA, follow=True)

        self.assertRedirects(response, CONTACT_URL)
        self.assertContains(
            response,
            "Votre message a bien été envoyé. Merci pour votre prise de contact.",
        )

    def test_missing_contact_email_returns_503_without_smtp_attempt(self):
        with override_settings(CONTACT_EMAIL=""), patch(
            "blog.views.EmailMessage.send"
        ) as send:
            response = self.client.post(CONTACT_URL, CONTACT_DATA)

        self.assertEqual(response.status_code, 503)
        send.assert_not_called()

    def test_missing_default_sender_returns_503_without_smtp_attempt(self):
        with override_settings(DEFAULT_FROM_EMAIL=""), patch(
            "blog.views.EmailMessage.send"
        ) as send:
            response = self.client.post(CONTACT_URL, CONTACT_DATA)

        self.assertEqual(response.status_code, 503)
        send.assert_not_called()

    def test_delivery_errors_return_503(self):
        errors = (SMTPException("SMTP indisponible"), OSError("réseau indisponible"))
        for error in errors:
            with self.subTest(exception_type=type(error).__name__), patch(
                "blog.views.EmailMessage.send", side_effect=error
            ):
                response = self.client.post(CONTACT_URL, CONTACT_DATA)

            self.assertEqual(response.status_code, 503)
            self.assertContains(
                response,
                "L’envoi du message a momentanément échoué.",
                status_code=503,
            )

    def test_delivery_failure_logs_no_exception_details_or_personal_data(self):
        sensitive_values = (
            settings.EMAIL_HOST_USER,
            "smtp-password-secret",
            CONTACT_DATA["prenom"],
            CONTACT_DATA["nom"],
            CONTACT_DATA["email"],
            CONTACT_DATA["message"],
        )
        error = SMTPException("smtp-password-secret ada@example.test")

        with patch("blog.views.EmailMessage.send", side_effect=error), self.assertLogs(
            "blog.views", level="ERROR"
        ) as captured:
            response = self.client.post(CONTACT_URL, CONTACT_DATA)

        self.assertEqual(response.status_code, 503)
        logs = "\n".join(captured.output)
        self.assertIn("operation=contact_email_delivery_failed", logs)
        self.assertIn("exception_type=SMTPException", logs)
        for sensitive_value in sensitive_values:
            self.assertNotIn(sensitive_value, logs)


class EmailSettingsTests(SimpleTestCase):
    def test_email_timeout_is_loaded_from_environment(self):
        with patch.dict(os.environ, {"EMAIL_TIMEOUT": "17"}):
            self.assertEqual(env_positive_int("EMAIL_TIMEOUT", 10), 17)

    def test_email_timeout_defaults_to_ten_seconds(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(env_positive_int("EMAIL_TIMEOUT", 10), 10)

    def test_smtp_backend_uses_global_timeout(self):
        with override_settings(EMAIL_TIMEOUT=7):
            self.assertEqual(EmailBackend().timeout, 7)

    def test_tls_and_ssl_cannot_both_be_enabled(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_email_transport_security(use_tls=True, use_ssl=True)
