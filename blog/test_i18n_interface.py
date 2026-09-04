from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from shop.models import Produit

from .forms import ContactForm


class GlobalInterfaceI18nTests(TestCase):
    def test_french_navigation_and_home_remain_the_default(self):
        response = self.client.get("/")

        self.assertContains(response, '<html lang="fr">')
        self.assertContains(response, ">Accueil<")
        self.assertContains(response, ">Articles<")
        self.assertContains(response, "Faire un don</a>")
        self.assertContains(response, ">Changer<")
        self.assertContains(response, "Des idées, des découvertes et une sélection pensée avec soin.")

    def test_german_navigation_selector_and_home_are_translated(self):
        response = self.client.get("/de/")

        self.assertContains(response, '<html lang="de">')
        self.assertContains(response, ">Startseite<")
        self.assertContains(response, ">Artikel<")
        self.assertContains(response, "Spenden</a>")
        self.assertContains(response, ">Ändern<")
        self.assertContains(
            response,
            "Ideen, Entdeckungen und eine Auswahl, die mit Sorgfalt zusammengestellt wurde.",
        )

    def test_english_navigation_selector_and_home_are_translated(self):
        response = self.client.get("/en/")

        self.assertContains(response, '<html lang="en">')
        self.assertContains(response, ">Home<")
        self.assertContains(response, ">Shop<")
        self.assertContains(response, "Donate</a>")
        self.assertContains(response, ">Change<")
        self.assertContains(response, "Ideas, discoveries and a selection chosen with care.")

    def test_about_page_is_translated_in_german_and_english(self):
        german = self.client.get("/de/about/")
        english = self.client.get("/en/about/")

        self.assertContains(german, "Ein Ort, um mit Vertrauen zu entdecken, zu verstehen und auszuwählen.")
        self.assertContains(german, "Unsere Vision")
        self.assertContains(english, "A place to explore, understand and choose with confidence.")
        self.assertContains(english, "Our vision")

    def test_contact_page_and_form_labels_are_translated(self):
        german = self.client.get("/de/contact/")
        english = self.client.get("/en/contact/")

        self.assertContains(german, "Sprechen wir über Ihre Idee.")
        self.assertContains(german, 'for="id_prenom">Vorname</label>')
        self.assertContains(german, 'for="id_email">E-Mail-Adresse</label>')
        self.assertContains(english, "Let’s talk about your idea.")
        self.assertContains(english, 'for="id_prenom">First name</label>')
        self.assertContains(english, 'for="id_email">Email address</label>')

    def test_contact_validation_errors_use_the_active_language(self):
        french = self.client.post("/contact/", {"prenom": "Ada"})
        german = self.client.post("/de/contact/", {"prenom": "Ada"})
        english = self.client.post("/en/contact/", {"prenom": "Ada"})

        self.assertContains(french, "Ce champ est obligatoire.")
        self.assertContains(german, "Dieses Feld ist erforderlich.")
        self.assertContains(english, "This field is required.")

    @override_settings(CONTACT_EMAIL="", EMAIL_HOST_USER="", DEFAULT_FROM_EMAIL="")
    def test_contact_error_message_is_translated_at_request_time(self):
        response = self.client.post(
            "/de/contact/",
            {
                "prenom": "Ada",
                "nom": "Lovelace",
                "email": "ada@example.test",
                "message": "Hallo",
            },
        )

        self.assertEqual(response.status_code, 503)
        self.assertContains(
            response,
            "Der Kontaktservice ist derzeit nicht verfügbar. Bitte versuchen Sie es später erneut.",
            status_code=503,
        )

    @patch("blog.views.EmailMessage.send", return_value=1)
    @override_settings(CONTACT_EMAIL="contact@example.test", DEFAULT_FROM_EMAIL="noreply@example.test")
    def test_contact_success_message_is_translated_at_request_time(self, send):
        response = self.client.post(
            "/en/contact/",
            {
                "prenom": "Ada",
                "nom": "Lovelace",
                "email": "ada@example.test",
                "message": "Hello",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(send.call_count, 1)
        self.assertContains(response, "Your message has been sent. Thank you for getting in touch.")

    def test_contact_form_uses_lazy_translated_labels(self):
        with translation.override("de"):
            self.assertEqual(str(ContactForm().fields["nom"].label), "Nachname")
        with translation.override("en"):
            self.assertEqual(str(ContactForm().fields["nom"].label), "Last name")

    def test_contact_thank_you_response_is_translated(self):
        self.assertContains(self.client.get("/de/remerciement/"), "Vielen Dank für Ihre Nachricht.")
        self.assertContains(self.client.get("/en/remerciement/"), "Thank you for your message.")

    def test_untranslated_dynamic_content_keeps_its_french_source_value(self):
        Produit.objects.create(
            nom="Produit français non traduit",
            description="Description française non traduite",
            prix="12.00",
            en_vedette=True,
        )

        response = self.client.get("/de/")

        self.assertContains(response, "Produit français non traduit")
        self.assertContains(response, "Description française non traduite")

    def test_payment_routes_are_unchanged_by_interface_translations(self):
        self.assertEqual(reverse("payments:stripe_webhook"), "/payments/webhook/")
        self.assertEqual(reverse("payments:cinetpay_ipn"), "/payments/cinetpay/ipn/")
        self.assertEqual(self.client.post("/de/payments/webhook/").status_code, 404)
