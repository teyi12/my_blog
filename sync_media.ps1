param(
    [string]$ProjectPathWindows,
    [string]$ProjectPathWSL
)

if (-not $ProjectPathWindows -or -not $ProjectPathWSL) {
    Write-Host "❌ Usage: .\sync_media.ps1 C:\Users\teyi1\my_blog /home/teyisomadje/projects/my_blog"
    exit 1
}

$BackupFile = Join-Path $ProjectPathWindows "media_backup.zip"
$MediaFolder = Join-Path $ProjectPathWindows "media"

if (-not (Test-Path $MediaFolder)) {
    Write-Host "❌ Dossier media introuvable dans $ProjectPathWindows"
    exit 1
}

# 1️⃣ Sauvegarde du dossier media sous Windows
Write-Host "📦 Compression du dossier media..."
Compress-Archive -Path "$MediaFolder\*" -DestinationPath $BackupFile -Force

# 2️⃣ Copie du fichier dans WSL
Write-Host "📤 Transfert vers WSL..."
$BackupFileWSL = "/mnt/c/" + ($BackupFile.Substring(3) -replace '\\','/')
wsl mkdir -p $ProjectPathWSL
wsl cp $BackupFileWSL "$ProjectPathWSL/media_backup.zip"

# 3️⃣ Extraction dans WSL
Write-Host "📂 Extraction dans WSL..."
wsl unzip -o "$ProjectPathWSL/media_backup.zip" -d "$ProjectPathWSL"

# 4️⃣ Nettoyage
Write-Host "🧹 Suppression du zip dans WSL..."
wsl rm "$ProjectPathWSL/media_backup.zip"

Write-Host "✅ Synchronisation terminée !"
