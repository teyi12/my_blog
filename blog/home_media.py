from django.contrib.staticfiles import finders
from django.templatetags.static import static


HERO_IMAGE = "images/home-hero.jpg"
HERO_FALLBACK_IMAGE = "images/home-hero-fallback.svg"


def home_hero_image_url():
    """Return a versioned static Hero image, with a bundled safe fallback."""
    image_name = HERO_IMAGE if finders.find(HERO_IMAGE) else HERO_FALLBACK_IMAGE
    return static(image_name)
