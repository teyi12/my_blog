from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.test import TestCase

from .home_media import HERO_FALLBACK_IMAGE, HERO_IMAGE


class HomeHeroMediaTests(TestCase):
    def test_available_image_is_a_versioned_static_asset_in_every_language(self):
        expected_alts = {
            "/": "Un carnet de voyage posé sur une carte, symbole de récits et de découvertes",
            "/de/": "Ein Reisetagebuch auf einer Karte, Sinnbild für Geschichten und Entdeckungen",
            "/en/": "A travel notebook on a map, symbolising stories and discoveries",
        }

        for path, alt in expected_alts.items():
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertContains(response, f'src="{static(HERO_IMAGE)}"')
                self.assertContains(response, f'alt="{alt}"')
                self.assertNotContains(response, f'{settings.MEDIA_URL}voyages.jpg')
                self.assertNotContains(response, 'src=""')

    def test_missing_primary_image_uses_the_bundled_fallback(self):
        with patch("blog.home_media.finders.find", return_value=None):
            response = self.client.get("/en/")

        self.assertContains(response, f'src="{static(HERO_FALLBACK_IMAGE)}"')
        self.assertNotContains(response, 'src=""')

    def test_fallback_asset_is_available_to_staticfiles(self):
        self.assertIsNotNone(finders.find(HERO_IMAGE))
        self.assertIsNotNone(finders.find(HERO_FALLBACK_IMAGE))
