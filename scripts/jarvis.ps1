# Enciende, apaga o revisa JARVIS con un solo comando.
#
#   .\scripts\jarvis.ps1 iniciar        base de datos + Ollama + API (http://localhost:8000)
#   .\scripts\jarvis.ps1 detener        libera RAM y GPU: apaga la API, descarga los modelos
#                                       y detiene la base de datos de JARVIS
#   .\scripts\jarvis.ps1 detener -TodoDocker   además apaga Docker/WSL (libera ~2 GB más;
#                                       detiene también los contenedores de otros proyectos)
#   .\scripts\jarvis.ps1 estado         qué está corriendo y cuánta memoria queda

param(
    [ValidateSet("iniciar", "detener", "estado")]
    [string]$Accion = "estado",
    [switch]$TodoDocker
)

# "Continue": docker y ollama escriben avisos normales en stderr; los errores reales se
# manejan con throw. (En PowerShell 5.1, "Stop" convertiría esos avisos en errores.)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root ".jarvis-api.pid"
$python = Join-Path $root ".venv\Scripts\python.exe"

function Write-Paso($texto) { Write-Host "-> $texto" -ForegroundColor Cyan }

function Test-Docker {
    docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Start-DockerDesktop {
    if (Test-Docker) { return }
    $exe = @(
        "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe",
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $exe) { throw "No se encontró Docker Desktop." }
    Write-Paso "Abriendo Docker Desktop (tarda ~30 s)"
    Start-Process $exe
    for ($i = 0; $i -lt 45; $i++) {
        Start-Sleep -Seconds 2
        if (Test-Docker) { return }
    }
    throw "Docker no respondió a tiempo."
}

function Get-ApiProcess {
    if (-not (Test-Path $pidFile)) { return $null }
    $apiPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($apiPid) { return Get-Process -Id $apiPid -ErrorAction SilentlyContinue }
    return $null
}

function Show-Estado {
    $os = Get-CimInstance Win32_OperatingSystem
    "RAM libre: {0:N1} GB de {1:N1} GB" -f ($os.FreePhysicalMemory / 1MB), ($os.TotalVisibleMemorySize / 1MB)
    $api = Get-ApiProcess
    "API JARVIS: " + ($(if ($api) { "encendida (PID $($api.Id))" } else { "apagada" }))
    if (Test-Docker) {
        $db = docker ps --filter "name=jarvis_db" --format "{{.Status}}"
        "Base de datos: " + ($(if ($db) { $db } else { "detenida" }))
    } else {
        "Base de datos: Docker apagado"
    }
    "Modelos cargados en Ollama:"
    ollama ps 2>$null
}

switch ($Accion) {
    "iniciar" {
        Start-DockerDesktop
        Write-Paso "Base de datos"
        Push-Location $root
        try { docker compose up -d 2>&1 | Out-Null } finally { Pop-Location }
        Write-Paso "Ollama"
        if (-not (Get-Process -Name "ollama" -ErrorAction SilentlyContinue)) {
            Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
            Start-Sleep -Seconds 4
        }
        if (Get-ApiProcess) {
            Write-Paso "La API ya estaba encendida"
        } else {
            Write-Paso "API en http://localhost:8000"
            $proc = Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
                -WorkingDirectory $root -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $root "logs\api.log") -RedirectStandardError (Join-Path $root "logs\api-error.log")
            $proc.Id | Set-Content $pidFile
        }
        Write-Host "JARVIS listo: http://localhost:8000" -ForegroundColor Green
    }
    "detener" {
        $api = Get-ApiProcess
        if ($api) {
            Write-Paso "Apagando la API"
            Stop-Process -Id $api.Id -Force
        }
        Remove-Item $pidFile -ErrorAction SilentlyContinue
        Write-Paso "Descargando modelos de la GPU y la RAM"
        $loaded = ollama ps 2>$null | Select-Object -Skip 1 | ForEach-Object { ($_ -split "\s+")[0] } | Where-Object { $_ }
        foreach ($model in $loaded) { ollama stop $model 2>$null | Out-Null }
        if (Test-Docker) {
            Write-Paso "Deteniendo la base de datos de JARVIS"
            Push-Location $root
            try { docker compose stop 2>&1 | Out-Null } finally { Pop-Location }
            if ($TodoDocker) {
                Write-Paso "Apagando Docker y WSL"
                Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process -Force
                wsl --shutdown
            }
        }
        Write-Host "JARVIS detenido." -ForegroundColor Green
        Show-Estado
    }
    "estado" { Show-Estado }
}
