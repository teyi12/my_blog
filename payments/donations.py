from django.conf import settings


LIVE_SECRET_KEY_PREFIXES = ("sk_live_", "rk_live_")


def donations_are_available():
    """Return whether creation of new Stripe donations is safely enabled."""
    if getattr(settings, "DONATIONS_ENABLED", False) is not True:
        return False

    secret_key = str(getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()
    webhook_secret = str(
        getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or ""
    ).strip()
    if not secret_key or not webhook_secret:
        return False

    if getattr(settings, "IS_PRODUCTION", False):
        return secret_key.startswith(LIVE_SECRET_KEY_PREFIXES)

    return True
