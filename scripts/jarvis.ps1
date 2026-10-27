# Enciende, apaga o revisa JARVIS con un solo comando.
#
#   .\scripts\jarvis.ps1 iniciar        base de datos + Ollama + API (http://localhost:8000) + worker
#   .\scripts\jarvis.ps1 iniciar -Gpu   igual, pero el worker indexa en la GPU (modo noche)
#   .\scripts\jarvis.ps1 iniciar -SinVoz   sin el agente de voz (micrófono apagado)
#   .\scripts\jarvis.ps1 iniciar -SinRed   sin Caddy (sólo en este PC: http://localhost:8000)
#   (si Caddy está instalado, también arranca HTTPS para la red de la casa: Etapa 11)
#   (por defecto también arranca el agente de voz: micrófono siempre activo, "Jarvis, …")
#   .\scripts\jarvis.ps1 detener        libera RAM y GPU: apaga la API, descarga los modelos
#                                       y detiene la base de datos de JARVIS
#   .\scripts\jarvis.ps1 detener -TodoDocker   además apaga Docker/WSL (libera ~2 GB más;
#                                       detiene también los contenedores de otros proyectos)
#   .\scripts\jarvis.ps1 estado         qué está corriendo y cuánta memoria queda

param(
    [ValidateSet("iniciar", "detener", "estado")]
    [string]$Accion = "estado",
    [switch]$TodoDocker,
    [switch]$Gpu,
    [switch]$SinVoz,
    [switch]$SinRed
)

# "Continue": docker y ollama escriben avisos normales en stderr; los errores reales se
# manejan con throw. (En PowerShell 5.1, "Stop" convertiría esos avisos en errores.)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root ".jarvis-api.pid"
$workerPidFile = Join-Path $root ".jarvis-worker.pid"
$voicePidFile = Join-Path $root ".jarvis-voz.pid"
$caddyPidFile = Join-Path $root ".jarvis-caddy.pid"
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

function Get-PidProcess($file) {
    if (-not (Test-Path $file)) { return $null }
    $savedPid = Get-Content $file -ErrorAction SilentlyContinue
    if ($savedPid) { return Get-Process -Id $savedPid -ErrorAction SilentlyContinue }
    return $null
}

# El python.exe del entorno virtual es un lanzador que abre el intérprete real como
# proceso hijo: hay que cerrar el árbol completo, no sólo el PID guardado.
function Stop-Tree($proc) {
    if ($proc) { taskkill /PID $proc.Id /T /F 2>&1 | Out-Null }
}

function Get-ApiProcess { Get-PidProcess $pidFile }
function Get-WorkerProcess { Get-PidProcess $workerPidFile }
function Get-VoiceProcess { Get-PidProcess $voicePidFile }
function Get-CaddyProcess { Get-PidProcess $caddyPidFile }

function Get-CaddyExe {
    $cmd = Get-Command caddy -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $link = "$env:LOCALAPPDATA\Microsoft\WinGet\Links\caddy.exe"
    if (Test-Path $link) { return $link }
    # winget a veces no crea el atajo: el programa queda en Packages\CaddyServer.Caddy_*
    $pkg = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\CaddyServer.Caddy_*\caddy.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pkg) { return $pkg.FullName }
    return $null
}

# IP de este PC en la red de la casa (la de la conexión con salida a internet).
function Get-LanIp {
    $config = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } | Select-Object -First 1
    if ($config) { return $config.IPv4Address.IPAddress }
    return $null
}

function Show-Estado {
    $os = Get-CimInstance Win32_OperatingSystem
    "RAM libre: {0:N1} GB de {1:N1} GB" -f ($os.FreePhysicalMemory / 1MB), ($os.TotalVisibleMemorySize / 1MB)
    $api = Get-ApiProcess
    "API JARVIS: " + ($(if ($api) { "encendida (PID $($api.Id))" } else { "apagada" }))
    $worker = Get-WorkerProcess
    "Worker de ingesta: " + ($(if ($worker) { "encendido (PID $($worker.Id))" } else { "apagado" }))
    $voice = Get-VoiceProcess
    "Agente de voz: " + ($(if ($voice) { "escuchando (PID $($voice.Id)) · registro en logs\voz.log" } else { "apagado" }))
    $caddy = Get-CaddyProcess
    "Red de la casa (Caddy): " + ($(if ($caddy) { "https://$(Get-LanIp) (PID $($caddy.Id))" } else { "apagada" }))
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
        New-Item -ItemType Directory -Force -Path (Join-Path $root "logs") | Out-Null
        Write-Paso "Base de datos"
        Push-Location $root
        try { docker compose up -d 2>&1 | Out-Null } finally { Pop-Location }
        Write-Paso "Ollama"
        if (-not (Get-Process -Name "ollama" -ErrorAction SilentlyContinue)) {
            Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
            Start-Sleep -Seconds 4
        }
        # Precarga el modelo de chat en la GPU (~10 s) para que la primera pregunta no espere.
        Write-Paso "Cargando el modelo de chat en la GPU"
        try {
            $model = (Get-Content (Join-Path $root ".env") -ErrorAction SilentlyContinue | Where-Object { $_ -match "^OLLAMA_CHAT_MODEL=" }) -replace "^OLLAMA_CHAT_MODEL=", ""
            if (-not $model) { $model = "jarvis:base" }
            Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/generate" -Method Post -TimeoutSec 120 `
                -Body (@{ model = $model; keep_alive = "5m" } | ConvertTo-Json) -ContentType "application/json" | Out-Null
        } catch {
            Write-Host "   (no se pudo precargar: se cargará con la primera pregunta)" -ForegroundColor Yellow
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
        if (Get-WorkerProcess) {
            Write-Paso "El worker ya estaba encendido"
        } else {
            $workerArgs = @("-m", "worker")
            if ($Gpu) { $workerArgs += "--gpu" }
            Write-Paso ("Worker de ingesta (" + $(if ($Gpu) { "GPU" } else { "CPU, prioridad baja" }) + ")")
            $wproc = Start-Process -FilePath $python -ArgumentList $workerArgs `
                -WorkingDirectory $root -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $root "logs\worker.log") -RedirectStandardError (Join-Path $root "logs\worker-error.log")
            $wproc.Id | Set-Content $workerPidFile
        }
        if (-not $SinVoz) {
            if (Get-VoiceProcess) {
                Write-Paso "El agente de voz ya estaba encendido"
            } else {
                # Espera a que la API responda: el agente la necesita para arrancar.
                for ($i = 0; $i -lt 30; $i++) {
                    try { if ((Invoke-WebRequest "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { break } } catch {}
                    Start-Sleep -Seconds 1
                }
                Write-Paso 'Agente de voz: micrófono activo, diga "Jarvis, …" (registro en logs\voz.log)'
                $vproc = Start-Process -FilePath $python -ArgumentList "-m", "agents.voice" `
                    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
                    -RedirectStandardOutput (Join-Path $root "logs\voz.log") -RedirectStandardError (Join-Path $root "logs\voz-error.log")
                $vproc.Id | Set-Content $voicePidFile
            }
        }
        $lanUrl = $null
        if (-not $SinRed) {
            $caddyExe = Get-CaddyExe
            $ip = Get-LanIp
            if (Get-CaddyProcess) {
                Write-Paso "Caddy ya estaba encendido"
                $lanUrl = "https://$ip"
            } elseif ($caddyExe -and $ip) {
                Write-Paso "Red de la casa: https://$ip (Caddy)"
                $env:JARVIS_IP = $ip
                $cproc = Start-Process -FilePath $caddyExe -ArgumentList "run", "--config", "deploy\caddy\Caddyfile", "--adapter", "caddyfile" `
                    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
                    -RedirectStandardOutput (Join-Path $root "logs\caddy.log") -RedirectStandardError (Join-Path $root "logs\caddy-error.log")
                $cproc.Id | Set-Content $caddyPidFile
                $lanUrl = "https://$ip"
            } elseif (-not $caddyExe) {
                Write-Host "   (Caddy no está instalado: sólo en este PC. Ver scripts\red_local.ps1)" -ForegroundColor Yellow
            }
        }
        Write-Host "JARVIS listo: http://localhost:8000" -ForegroundColor Green
        if ($lanUrl) { Write-Host "Desde el celular (misma Wi-Fi): $lanUrl" -ForegroundColor Green }
    }
    "detener" {
        $api = Get-ApiProcess
        if ($api) {
            Write-Paso "Apagando la API"
            Stop-Tree $api
        }
        Remove-Item $pidFile -ErrorAction SilentlyContinue
        $voice = Get-VoiceProcess
        if ($voice) {
            Write-Paso "Apagando el agente de voz (micrófono)"
            Stop-Tree $voice
        }
        Remove-Item $voicePidFile -ErrorAction SilentlyContinue
        $caddy = Get-CaddyProcess
        if ($caddy) {
            Write-Paso "Apagando Caddy (red de la casa)"
            Stop-Tree $caddy
        }
        Remove-Item $caddyPidFile -ErrorAction SilentlyContinue
        $worker = Get-WorkerProcess
        if ($worker) {
            Write-Paso "Apagando el worker (las tareas en curso se retoman al volver a iniciar)"
            Stop-Tree $worker
        }
        Remove-Item $workerPidFile -ErrorAction SilentlyContinue
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
