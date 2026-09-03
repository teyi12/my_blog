from pathlib import Path
import os
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT == "production" or bool(os.getenv("RENDER"))
DEBUG = env_bool("DEBUG", default=not IS_PRODUCTION)

SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise ImproperlyConfigured("SECRET_KEY doit être définie en production.")
    SECRET_KEY = "unsafe-dev-key"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# -----------------------------------------------------------------------------
# Base de données
# SQLite en développement, PostgreSQL via DATABASE_URL en production.
# Exemple : postgresql://user:password@host:5432/dbname
# -----------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if DATABASE_URL:
    parsed_db = urlparse(DATABASE_URL)
    if parsed_db.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("DATABASE_URL doit utiliser PostgreSQL.")

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed_db.path.lstrip("/")),
            "USER": unquote(parsed_db.username or ""),
            "PASSWORD": unquote(parsed_db.password or ""),
            "HOST": parsed_db.hostname or "",
            "PORT": str(parsed_db.port or 5432),
            "CONN_MAX_AGE": 60,
            "OPTIONS": {
                "sslmode": os.getenv(
                    "DATABASE_SSLMODE",
                    "require" if IS_PRODUCTION else "prefer",
                ),
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# -----------------------------------------------------------------------------
# E-mail
# -----------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "").strip()
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER).strip()
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "http://127.0.0.1:8800").rstrip("/")

# -----------------------------------------------------------------------------
# Applications
# -----------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "rest_framework",
    "sslserver",
    "articles",
    "accounts",
    "shop",
    "payments",
    "social",
    "monetization",
]

SITE_ID = 1
AUTH_USER_MODEL = "accounts.CustomUser"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -----------------------------------------------------------------------------
# Middleware
# WhiteNoise est placé juste après SecurityMiddleware afin de servir les
# fichiers statiques collectés sur Render, sans dépendre d'un serveur séparé.
# -----------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

# -----------------------------------------------------------------------------
# Templates / WSGI
# -----------------------------------------------------------------------------
ROOT_URLCONF = "blog.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "shop.context_processors.panier_counter",
            ],
        },
    },
]

WSGI_APPLICATION = "blog.wsgi.application"

# -----------------------------------------------------------------------------
# Authentification / mots de passe
# -----------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"
LOGIN_URL = "/accounts/login/"

# -----------------------------------------------------------------------------
# Internationalisation
# -----------------------------------------------------------------------------
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = os.getenv("TIME_ZONE", "Europe/Berlin")
USE_I18N = True
USE_TZ = True

# -----------------------------------------------------------------------------
# Fichiers statiques et médias
# Les médias utilisateurs restent séparés des statiques. WhiteNoise ne doit
# pas être utilisé comme stockage persistant des médias uploadés.
# -----------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if IS_PRODUCTION
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
}

# -----------------------------------------------------------------------------
# Sécurité HTTP
# Ces paramètres sont activés uniquement en production afin de préserver le
# développement local sur http://127.0.0.1:8800.
# -----------------------------------------------------------------------------
if IS_PRODUCTION:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "3600"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
    SECURE_CONTENT_TYPE_NOSNIFF = True
else:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

# -----------------------------------------------------------------------------
# Stripe
# -----------------------------------------------------------------------------
STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_MONTHLY = os.getenv("STRIPE_PRICE_MONTHLY", "")
PAYMENT_PROCESSING_TIMEOUT_SECONDS = int(
    os.getenv("PAYMENT_PROCESSING_TIMEOUT_SECONDS", "3600")
)

# -----------------------------------------------------------------------------
# Mobile Money
# -----------------------------------------------------------------------------
MOBILE_MONEY_API_KEY = os.getenv("MOBILE_MONEY_API_KEY")
MOBILE_MONEY_SECRET_KEY = os.getenv("MOBILE_MONEY_SECRET_KEY")
MOBILE_MONEY_BASE_URL = os.getenv(
    "MOBILE_MONEY_BASE_URL",
    "https://app.paydunya.com/api/v1/checkout-invoice/create",
)

# -----------------------------------------------------------------------------
# CinetPay
# -----------------------------------------------------------------------------
CINETPAY_API_KEY = os.getenv("CINETPAY_API_KEY", "")
CINETPAY_SITE_ID = os.getenv("CINETPAY_SITE_ID", "")
CINETPAY_BASE_URL = os.getenv(
    "CINETPAY_BASE_URL",
    "https://api-checkout.cinetpay.com/v2",
)
PAYMENT_MINIMUM_AMOUNTS = {
    "EUR": os.getenv("PAYMENT_MINIMUM_AMOUNT_EUR", "0.50"),
    "USD": os.getenv("PAYMENT_MINIMUM_AMOUNT_USD", "0.50"),
    "XOF": os.getenv("PAYMENT_MINIMUM_AMOUNT_XOF", "500"),
}
