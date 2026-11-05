<#
.SYNOPSIS
    Protocolo Odiseo, segunda capa: el Firewall de Windows impide que los programas de
    JARVIS salgan a internet.

.DESCRIPTION
    La primera capa vive dentro de JARVIS (app/core/odiseo.py) y bloquea toda conexión que
    no sea a este mismo PC. Esta segunda capa la pone Windows, por fuera de JARVIS: aunque
    alguien cambiara el código, Ollama y Caddy no podrían conectarse a internet.

    Crea reglas de SALIDA "Bloquear" hacia "Internet" (todo lo que no es la red de la casa)
    para:
      - Ollama (el modelo de lenguaje).
      - Caddy (el HTTPS para el celular). Los celulares de la casa siguen entrando.
      - Opcional, con -IncluirPython: el Python que usa JARVIS. OJO: es el mismo Python de
        todo el PC, así que también dejaría sin internet a pip y a otros programas en Python.

    Ollama y Caddy siguen funcionando igual dentro del PC y en la red de la casa.

    Debe ejecutarse en una PowerShell abierta como administrador.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\odiseo_firewall.ps1
    powershell -ExecutionPolicy Bypass -File .\scripts\odiseo_firewall.ps1 -Estado
    powershell -ExecutionPolicy Bypass -File .\scripts\odiseo_firewall.ps1 -Quitar

    Para descargar un modelo nuevo (ollama pull) hay que quitar las reglas, descargar y
    volver a ponerlas.
#>
param(
    [switch]$Quitar,
    [switch]$Estado,
    [switch]$IncluirPython
)

$ErrorActionPreference = "Stop"
$Group = "JARVIS Odiseo"
$Root = Split-Path -Parent $PSScriptRoot

function Show-Rules {
    $rules = Get-NetFirewallRule -Group $Group -ErrorAction SilentlyContinue
    if (-not $rules) {
        "Protocolo Odiseo (firewall): sin reglas."
        return
    }
    "Protocolo Odiseo (firewall): reglas activas"
    foreach ($rule in $rules) {
        $app = ($rule | Get-NetFirewallApplicationFilter).Program
        "  {0}  ->  {1}" -f $rule.DisplayName, $app
    }
}

if ($Estado) { Show-Rules; exit 0 }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "Abra PowerShell como administrador (clic derecho > Ejecutar como administrador) y repita." -ForegroundColor Yellow
    exit 1
}

if ($Quitar) {
    Get-NetFirewallRule -Group $Group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Write-Host "Reglas del Protocolo Odiseo quitadas del firewall." -ForegroundColor Yellow
    Write-Host "La primera capa (dentro de JARVIS) sigue activa mientras ODISEO=true en .env."
    exit 0
}

# ---------- Qué programas bloquear ----------

$programs = [ordered]@{}

$ollamaDir = "$env:LOCALAPPDATA\Programs\Ollama"
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaCmd) { $ollamaDir = Split-Path -Parent $ollamaCmd.Source }
foreach ($name in "ollama.exe", "ollama app.exe") {
    $path = Join-Path $ollamaDir $name
    if (Test-Path $path) { $programs["Ollama ($name)"] = $path }
}

$caddy = Get-Command caddy -ErrorAction SilentlyContinue
$caddyPath = if ($caddy) { $caddy.Source } else { $null }
if (-not $caddyPath) {
    $pkg = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\CaddyServer.Caddy_*\caddy.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pkg) { $caddyPath = $pkg.FullName }
}
if ($caddyPath) {
    # El atajo de winget apunta al programa real: se bloquea el programa real.
    $item = Get-Item $caddyPath
    if ($item.LinkType -and $item.Target) { $caddyPath = @($item.Target)[0] }
    $programs["Caddy"] = $caddyPath
}

if ($IncluirPython) {
    $venv = Join-Path $Root ".venv"
    $cfg = Join-Path $venv "pyvenv.cfg"
    if (Test-Path $cfg) {
        $homeLine = Get-Content $cfg | Where-Object { $_ -match "^home\s*=" } | Select-Object -First 1
        if ($homeLine) {
            $base = Join-Path ($homeLine -replace "^home\s*=\s*", "").Trim() "python.exe"
            if (Test-Path $base) { $programs["Python (de todo el PC)"] = $base }
        }
        $venvPython = Join-Path $venv "Scripts\python.exe"
        if (Test-Path $venvPython) { $programs["Python de JARVIS (.venv)"] = $venvPython }
    }
}

if ($programs.Count -eq 0) {
    Write-Host "No encontré Ollama ni Caddy en este PC." -ForegroundColor Yellow
    exit 1
}

# ---------- Reglas ----------

Get-NetFirewallRule -Group $Group -ErrorAction SilentlyContinue | Remove-NetFirewallRule

foreach ($entry in $programs.GetEnumerator()) {
    New-NetFirewallRule `
        -DisplayName "JARVIS Odiseo - $($entry.Key) sin internet" `
        -Group $Group `
        -Description "Protocolo Odiseo: JARVIS no se conecta a internet. Quitar con scripts\odiseo_firewall.ps1 -Quitar" `
        -Direction Outbound `
        -Action Block `
        -Program $entry.Value `
        -RemoteAddress Internet `
        -Profile Any | Out-Null
}

Write-Host "Protocolo Odiseo activo en el firewall." -ForegroundColor Green
Show-Rules
Write-Host ""
Write-Host "Siguen funcionando: el chat en este PC y desde los celulares de la casa."
Write-Host "Para descargar un modelo nuevo: -Quitar, ollama pull ..., y volver a ejecutar este script."
