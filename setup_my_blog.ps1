# setup_my_blog.ps1
Write-Host "`n📁 Création de l'environnement virtuel si non existant..."
if (-Not (Test-Path "venv")) {
    python -m venv venv
}

Write-Host "✅ Activation de l'environnement virtuel..."
& .\venv\Scripts\Activate.ps1

Write-Host "`n📦 Installation des dépendances..."
pip install --upgrade pip
if (Test-Path "requirements.txt") {
    pip install -r requirements.txt
} else {
    Write-Host "⚠️ Aucun requirements.txt trouvé."
}

# 🔍 Vérifie si STATIC_ROOT est défini dans settings.py
$settingsPath = Get-ChildItem -Path . -Recurse -Filter settings.py | Select-Object -First 1

if ($settingsPath) {
    $settingsContent = Get-Content $settingsPath.FullName
    if ($settingsContent -notmatch "STATIC_ROOT") {
        Write-Host "`n🛠️ Ajout de STATIC_ROOT à settings.py..."
        Add-Content $settingsPath.FullName "`nSTATIC_ROOT = BASE_DIR / 'staticfiles'"
    } else {
        Write-Host "✅ STATIC_ROOT est déjà défini."
    }
} else {
    Write-Host "❌ settings.py introuvable !"
    exit 1
}

Write-Host "`n⚙️ Application des migrations..."
python manage.py makemigrations
python manage.py migrate

Write-Host "`n🧙‍♂️ Collecte des fichiers statiques..."
python manage.py collectstatic --noinput

Write-Host "`n🚀 Lancement du serveur Django..."
python manage.py runserver
