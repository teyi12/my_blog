#!/bin/bash

echo "🔐 Création du dossier SSL et génération des certificats..."
mkdir -p certs
openssl req -x509 -newkey rsa:4096 -keyout certs/key.pem -out certs/cert.pem -days 365 -nodes -subj "/C=FR/ST=Dev/L=Local/O=LocalDev/OU=Dev/CN=localhost"

echo "📦 Installation de django-sslserver..."
pip install django-sslserver

echo "⚙️ Ajout automatique de 'sslserver' dans settings.py..."

python <<EOF
import re
from pathlib import Path

settings_path = Path("blog/settings.py")
content = settings_path.read_text()

if "'sslserver'" not in content:
    new_content = re.sub(
        r"(INSTALLED_APPS\s*=\s*\[)",
        r"\1\n    'sslserver',",
        content
    )
    settings_path.write_text(new_content)
    print("✅ 'sslserver' ajouté à INSTALLED_APPS.")
else:
    print("ℹ️ 'sslserver' est déjà présent dans INSTALLED_APPS.")
EOF

echo ""
echo "🎉 Configuration terminée !"
echo "➡️ Pour lancer le serveur HTTPS :"
echo "python manage.py runsslserver --certificate certs/cert.pem --key certs/key.pem"
