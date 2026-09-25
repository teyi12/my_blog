#!/usr/bin/env bash
set -o errexit
set -o nounset
set -o pipefail

python -m pip install -r requirements.txt
# Plan Render gratuit : déplacer cette migration vers Pre-Deploy dès qu’il est disponible.
python manage.py migrate --noinput
python manage.py collectstatic --noinput
