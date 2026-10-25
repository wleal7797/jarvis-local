# Copia de seguridad de la base de datos de JARVIS.
# Uso:  .\scripts\backup_db.ps1            (guarda en .\backups, ignorado por Git)
#       .\scripts\backup_db.ps1 -Keep 14   (conserva sólo las 14 copias más recientes)
#
# Restaurar una copia:
#   docker cp .\backups\<archivo>.dump jarvis_db:/tmp/restore.dump
#   docker exec jarvis_db pg_restore -U jarvis -d jarvis --clean --if-exists /tmp/restore.dump

param(
    [int]$Keep = 7,
    [string]$Container = "jarvis_db",
    [string]$Database = "jarvis",
    [string]$User = "jarvis"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backupDir = Join-Path $root "backups"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$fileName = "jarvis_$stamp.dump"
$remote = "/tmp/$fileName"

# Formato personalizado (-Fc): comprimido y restaurable por tablas.
# Se escribe dentro del contenedor y luego se copia, porque PowerShell 5.1
# corrompe los archivos binarios si se redirige la salida con ">".
docker exec $Container pg_dump -U $User -d $Database -Fc -f $remote
if ($LASTEXITCODE -ne 0) { throw "pg_dump falló" }
docker cp "${Container}:$remote" (Join-Path $backupDir $fileName) | Out-Null
docker exec $Container rm -f $remote | Out-Null

$size = [math]::Round((Get-Item (Join-Path $backupDir $fileName)).Length / 1KB, 1)
Write-Output "Copia creada: backups\$fileName ($size KB)"

Get-ChildItem $backupDir -Filter "jarvis_*.dump" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip $Keep |
    ForEach-Object { Remove-Item $_.FullName; Write-Output "Copia antigua borrada: $($_.Name)" }
