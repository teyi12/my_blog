#!/bin/bash

set -e

PROJECT="my_blog"
APPS=("accounts" "products" "cart" "orders" "payments" "core")

print_section() {
    echo -e "\n\033[1;34m🔧 $1\033[0m"
}

print_success() {
    echo -e "\033[1;32m✅ $1\033[0m"
}

print_section "Création du projet Django : $PROJECT"
mkdir -p $PROJECT/{apps,templates,static,media,config/settings}
cd $PROJECT

print_section "Fichiers principaux : manage.py, requirements, Procfile, .env"

cat > manage.py <<EOF
#!/usr/bin/env python
import os, sys
if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
EOF

cat > requirements.txt <<EOF
Django>=4.2
gunicorn
psycopg2-binary
whitenoise
python-dotenv
django-storages
boto3
EOF

echo "web: gunicorn config.wsgi" > Procfile
echo "python-3.11" > runtime.txt

cat > .env <<EOF
SECRET_KEY=dev-secret-key
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost

POSTGRES_DB=ecommerce_db
POSTGRES_USER=postgres
POSTGRES_PASSWORD=motdepasse
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
EOF

print_section "Configuration Django (config/settings)"

cat > config/__init__.py <<EOF
EOF

cat > config/asgi.py <<EOF
import os
from django.core.asgi import get_asgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
application = get_asgi_application()
EOF

cat > config/wsgi.py <<EOF
import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
application = get_wsgi_application()
EOF

cat > config/settings/__init__.py <<EOF
EOF

cat > config/settings/base.py <<EOF
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SECRET_KEY = os.getenv('SECRET_KEY')
DEBUG = os.getenv('DEBUG', 'False') == 'True'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'whitenoise.runserver_nostatic',
    'apps.accounts',
    'apps.products',
    'apps.cart',
    'apps.orders',
    'apps.payments',
    'apps.core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.debug',
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
        ],
    },
}]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv("POSTGRES_DB"),
        'USER': os.getenv("POSTGRES_USER"),
        'PASSWORD': os.getenv("POSTGRES_PASSWORD"),
        'HOST': os.getenv("POSTGRES_HOST", "localhost"),
        'PORT': os.getenv("POSTGRES_PORT", "5432"),
    }
}

LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Europe/Paris'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
EOF

cat > config/settings/dev.py <<EOF
from .base import *

DEBUG = True
ALLOWED_HOSTS = ['*']
EOF

cat > config/settings/prod.py <<EOF
from .base import *

DEBUG = False
ALLOWED_HOSTS = ['ecommerce-production.up.railway.app']

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
EOF

print_section "Création des apps Django"

for app in "${APPS[@]}"; do
    mkdir -p apps/$app
    touch apps/$app/{__init__.py,models.py,views.py,urls.py,admin.py}

    echo "from django.urls import path" > apps/$app/urls.py
    echo "urlpatterns = []" >> apps/$app/urls.py

    echo "from django.shortcuts import render" > apps/$app/views.py

    print_success "App $app créée."
done

cat > apps/core/views.py <<EOF
from django.shortcuts import render

def home(request):
    return render(request, "home.html")
EOF

print_section "Création des templates HTML"

cat > templates/base.html <<EOF
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}E-commerce{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand" href="#">E-commerce</a>
        </div>
    </nav>
    <div class="container mt-4">
        {% block content %}{% endblock %}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
EOF

cat > templates/home.html <<EOF
{% extends "base.html" %}
{% block title %}Accueil{% endblock %}
{% block content %}
  <div class="text-center">
    <h1 class="display-4">Bienvenue sur notre boutique !</h1>
    <p class="lead">Projet Django + Bootstrap prêt pour Railway 🚀</p>
  </div>
{% endblock %}
EOF

print_section "Configuration des routes (urls.py)"

cat > config/urls.py <<EOF
from django.contrib import admin
from django.urls import path, include
from apps.core.views import home

urlpatterns = [
    path('', home, name='home'),
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('products/', include('apps.products.urls')),
    path('cart/', include('apps.cart.urls')),
    path('orders/', include('apps.orders.urls')),
    path('payments/', include('apps.payments.urls')),
]
EOF

print_success "Projet Django e-commerce prêt 🎉"
echo -e "\n➡️  cd $PROJECT"
echo "➡️  python -m venv venv && source venv/bin/activate"
echo "➡️  pip install -r requirements.txt"
echo "➡️  python manage.py migrate"
echo "➡️  python manage.py runserver --settings=config.settings.dev"
