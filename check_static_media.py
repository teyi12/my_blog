import os
import django
from django.conf import settings

# Configure Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "blog.settings")
django.setup()

print("🔍 Vérification des réglages Django...")

# Vérifier STATIC et MEDIA
print(f"STATIC_URL  = {settings.STATIC_URL}")
print(f"STATIC_ROOT = {settings.STATIC_ROOT}")
print(f"MEDIA_URL   = {settings.MEDIA_URL}")
print(f"MEDIA_ROOT  = {settings.MEDIA_ROOT}")

# Vérifier existence des dossiers
if os.path.exists(settings.STATIC_ROOT):
    print(f"✅ Dossier STATIC_ROOT trouvé : {settings.STATIC_ROOT}")
else:
    print(f"❌ STATIC_ROOT inexistant : {settings.STATIC_ROOT}")

if os.path.exists(settings.MEDIA_ROOT):
    print(f"✅ Dossier MEDIA_ROOT trouvé : {settings.MEDIA_ROOT}")
else:
    print(f"❌ MEDIA_ROOT inexistant : {settings.MEDIA_ROOT}")

# Vérifier fichiers CSS
css_path = os.path.join(settings.STATIC_ROOT, "css")
if os.path.exists(css_path):
    css_files = [f for f in os.listdir(css_path) if f.endswith(".css")]
    if css_files:
        print(f"✅ {len(css_files)} fichiers CSS trouvés dans {css_path}: {', '.join(css_files)}")
    else:
        print(f"❌ Aucun fichier CSS trouvé dans {css_path}")
else:
    print(f"❌ Dossier CSS inexistant : {css_path}")

# Vérifier images articles
articles_path = os.path.join(settings.MEDIA_ROOT, "articles")
if os.path.exists(articles_path):
    images = [f for f in os.listdir(articles_path) if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
    if images:
        print(f"✅ {len(images)} images trouvées dans {articles_path}: {', '.join(images)}")
    else:
        print(f"⚠️ Aucune image trouvée dans {articles_path}")
else:
    print(f"❌ Dossier articles inexistant : {articles_path}")
