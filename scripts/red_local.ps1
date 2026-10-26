# Prepara este PC para que JARVIS se use desde el celular y otros equipos de la casa.
# Lo ejecuta USTED, como administrador, una sola vez (cambia la configuración de Windows):
#
#   Clic derecho en PowerShell > "Ejecutar como administrador", y luego:
#   cd "$env:USERPROFILE\OneDrive\Desktop\JARVIS v1.0"
#   powershell -ExecutionPolicy Bypass -File .\scripts\red_local.ps1
#
# Qué hace (y pregunta antes de cada paso):
#   1. Instala Caddy (servidor HTTPS) con winget, si no está.
#   2. Marca la red Wi-Fi/Ethernet actual como "Privada" (la de su casa).
#   3. Abre los puertos 80 y 443 SÓLO para redes privadas (no en cafés ni aeropuertos).
#   4. (Opcional) Confía en el certificado de Caddy en este PC.
#   Para deshacer: .\scripts\red_local.ps1 -Quitar

param([switch]$Quitar)

$ErrorActionPreference = "Stop"
$ruleName = "JARVIS - HTTPS en la red de la casa"

function Write-Paso($texto) { Write-Host "`n-> $texto" -ForegroundColor Cyan }
function Confirm-Paso($pregunta) {
    $r = Read-Host "$pregunta [s/N]"
    return $r -match "^(s|si|sí|y|yes)$"
}

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "Ejecute este script como administrador (clic derecho en PowerShell)." -ForegroundColor Yellow
    exit 1
}

if ($Quitar) {
    Write-Paso "Quitando la regla del firewall"
    Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Write-Host "Listo. JARVIS ya no se puede abrir desde otros equipos." -ForegroundColor Green
    exit 0
}

# 1. Caddy
Write-Paso "1. Caddy (HTTPS)"
$caddy = Get-Command caddy -ErrorAction SilentlyContinue
if ($caddy) {
    Write-Host "   Ya está instalado: $($caddy.Source)"
} elseif (Confirm-Paso "   Caddy no está instalado. ¿Instalarlo con winget (CaddyServer.Caddy, ~40 MB)?") {
    winget install --id CaddyServer.Caddy --exact --accept-source-agreements
    Write-Host "   Cierre y vuelva a abrir PowerShell para que Windows lo encuentre." -ForegroundColor Yellow
} else {
    Write-Host "   Sin Caddy no hay HTTPS: el micrófono del celular no funcionará." -ForegroundColor Yellow
}

# 2. Red privada
Write-Paso "2. Tipo de red"
$net = Get-NetConnectionProfile | Where-Object { $_.IPv4Connectivity -ne "Disconnected" } | Select-Object -First 1
$config = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } | Select-Object -First 1
$ip = $config.IPv4Address.IPAddress
Write-Host "   Red: $($net.Name) · tipo: $($net.NetworkCategory) · IP de este PC: $ip"
if ($net.NetworkCategory -ne "Private") {
    if (Confirm-Paso "   ¿Esta es la red de su casa? Se marcará como Privada") {
        Set-NetConnectionProfile -InterfaceIndex $net.InterfaceIndex -NetworkCategory Private
        Write-Host "   Marcada como Privada."
    } else {
        Write-Host "   Sin red privada, el firewall no dejará entrar a los celulares." -ForegroundColor Yellow
    }
}

# 3. Firewall
Write-Paso "3. Firewall de Windows"
if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
    Write-Host "   La regla ya existe."
} elseif (Confirm-Paso "   ¿Abrir los puertos 80 y 443 sólo en redes privadas?") {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP `
        -LocalPort 80, 443 -Profile Private -Action Allow | Out-Null
    Write-Host "   Regla creada: '$ruleName' (sólo red privada)."
}

# 4. Confiar en el certificado en este PC (opcional)
Write-Paso "4. Certificado en este PC (opcional)"
if ((Get-Command caddy -ErrorAction SilentlyContinue) -and
    (Confirm-Paso "   ¿Confiar en el certificado de Caddy en este PC? (para abrir https://$ip sin aviso)")) {
    caddy trust
}

Write-Host "`nListo. Ahora:" -ForegroundColor Green
Write-Host "  1. .\scripts\jarvis.ps1 iniciar      (enciende también Caddy)"
Write-Host "  2. En el celular, con la misma Wi-Fi: http://$ip/certificado  (instalar el certificado)"
Write-Host "  3. Luego abra: https://$ip"
Write-Host "  Guía completa: docs\02-acceso-desde-la-red-local.md"
Write-Host "  Consejo: reserve la IP $ip para este PC en su router (ver la guía)."
