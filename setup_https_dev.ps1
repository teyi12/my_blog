Write-Host "🔐 Création du dossier SSL..."
New-Item -ItemType Directory -Force -Path "./certs" | Out-Null

Write-Host "🔐 Génération du certificat SSL auto-signé..."
openssl req -x509 -newkey rsa:4096 -keyout certs/key.pem -out certs/cert.pem -days 365 -nodes -subj "/C=FR/ST=Dev/L=Local/O=LocalDev/OU=Dev/CN=localhost"

Write-Host "📦 Installation de django-sslserver via pip..."
pip install django-sslserver

# Modifier settings.py
$settingsPath = "blog\settings.py"
if (Test-Path $settingsPath) {
    $content = Get-Content $settingsPath
    if ($content -notmatch "'sslserver'") {
        Write-Host "⚙️ Ajout de 'sslserver' à INSTALLED_APPS..."
        $newContent = $content -replace '(?<=INSTALLED_APPS\s*=\s*\[)', "`r`n    'sslserver',"
        $newContent | Set-Content $settingsPath
        Write-Host "✅ 'sslserver' ajouté avec succès."
    } else {
        Write-Host "ℹ️ 'sslserver' est déjà présent dans INSTALLED_APPS."
} else {
    Write-Host "❌ settings.py non trouvé à l'emplacement $settingsPath"
}

Write-Host ""
Write-Host "🎉 Configuration terminée ! Lance maintenant :"
Write-Host "`npython manage.py runsslserver --certificate certs\cert.pem --key certs\key.pem`n"
