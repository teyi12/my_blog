# Utiliser Python 3.13.2
FROM python:3.13.2-slim

# Définir le répertoire de travail
WORKDIR /app

# Copier les dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier tout le projet
COPY . .

# Collecter les fichiers statiques
RUN python manage.py collectstatic --noinput

# Exposer le port utilisé par Gunicorn/Django
EXPOSE 8000

# Lancer l'application via Gunicorn
CMD ["gunicorn", "blog.wsgi:application", "--bind", "0.0.0.0:8000"]


