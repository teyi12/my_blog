#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate

if [[ -n "${DJANGO_SUPERUSER_EMAIL:-}" && -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]]; then
    python manage.py shell -c '
import os
from django.contrib.auth import get_user_model

User = get_user_model()
email = os.environ["DJANGO_SUPERUSER_EMAIL"]

user, created = User.objects.get_or_create(
    email=email,
    defaults={
        "first_name": os.environ.get("DJANGO_SUPERUSER_FIRST_NAME", ""),
        "last_name": os.environ.get("DJANGO_SUPERUSER_LAST_NAME", ""),
    },
)

user.first_name = os.environ.get("DJANGO_SUPERUSER_FIRST_NAME", user.first_name)
user.last_name = os.environ.get("DJANGO_SUPERUSER_LAST_NAME", user.last_name)
user.is_staff = True
user.is_superuser = True
user.is_active = True
user.set_password(os.environ["DJANGO_SUPERUSER_PASSWORD"])
user.save()

print("Superuser configured:", email)
'
fi#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate
