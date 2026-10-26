# 02 · Acceso desde otros dispositivos de la casa

Pregunta: **si entro a `localhost` desde cualquier dispositivo de mi casa, ¿entro a la app?**

**No.** `localhost` siempre significa "este mismo aparato". Si escribe `localhost` en su celular, el celular se busca a sí mismo, no al PC.
Los demás dispositivos usan la **dirección del PC dentro de su red** (por ejemplo `192.168.1.50`).

```
              Router de la casa (192.168.1.1)
        ┌─────────────┼──────────────┬──────────────┐
   PC servidor     Celular        Tablet         Otro PC
  192.168.1.50   192.168.1.71   192.168.1.80   192.168.1.92
        ▲              │              │              │
        └────────── https://192.168.1.50 ────────────┘

   En el PC:  Caddy (:443, HTTPS)  ──►  API de JARVIS (127.0.0.1:8000, sólo este PC)
```

Todo el tráfico se queda **dentro de su casa**. Nada pasa por internet.

---

## Cómo quedó (Etapa 11)

| Pieza | Qué hace |
|---|---|
| **API en `127.0.0.1:8000`** | No se abre a la red: sólo la ve este PC. |
| **Caddy** (`deploy/caddy/Caddyfile`) | Recibe en `https://<ip-del-pc>` y le pasa todo a la API. Crea su propia autoridad certificadora local: los certificados nunca se piden a internet. |
| **Firewall de Windows** | Puertos 80 y 443 abiertos **sólo en redes privadas** (su Wi‑Fi de casa), no en cafés ni aeropuertos. |
| **Inicio de sesión** | Usuarios con contraseña (Argon2) y roles. Sin sesión no se ve nada. |

¿Por qué HTTPS? Los navegadores **sólo permiten el micrófono** en `localhost` o en sitios **HTTPS**. Con `http://192.168.1.50` el celular no podría escucharle.

---

## Paso a paso

### 1. Preparar el PC (una sola vez, como administrador)

```powershell
# Clic derecho en PowerShell > "Ejecutar como administrador"
cd "$env:USERPROFILE\OneDrive\Desktop\JARVIS v1.0"
powershell -ExecutionPolicy Bypass -File .\scripts\red_local.ps1
```

Pregunta antes de cada paso: instala **Caddy** (winget), marca su Wi‑Fi como **red privada**, abre los puertos **80 y 443 sólo en redes privadas** y, si quiere, confía en el certificado en este PC. Para deshacerlo: `.\scripts\red_local.ps1 -Quitar`.

> Estos pasos cambian la configuración de seguridad de Windows: por eso los ejecuta usted y no JARVIS.

### 2. Encender JARVIS

```powershell
.\scripts\jarvis.ps1 iniciar
```

Si Caddy está instalado, al final dice: `Desde el celular (misma Wi-Fi): https://192.168.1.50`.

### 3. La primera vez: la contraseña del dueño
Abra `http://localhost:8000` en el PC. JARVIS pide elegir la contraseña del **dueño** (usuario `dueno`). Después, en **Usuarios** (menú lateral) puede agregar a la familia y a las visitas.

| Rol | Puede |
|---|---|
| **Dueño** | Todo, incluido agregar usuarios |
| **Familia** | Conversar, su propia memoria, subir documentos (los personales sólo los ve quien los sube), calificar respuestas |
| **Invitado** | Sólo conversar. No ve documentos ni recuerdos, y JARVIS no aprende nada de lo que dice |

### 4. Instalar el certificado en el celular (una vez por aparato)

Con el celular en la **misma Wi‑Fi**, abra **`http://<ip-del-pc>/certificado`** (con `http`, sin la "s"). Se descarga `jarvis-ca.crt`.

**Android**
1. Ajustes › Seguridad y privacidad › Más ajustes de seguridad › **Instalar desde el almacenamiento** (o "Cifrado y credenciales › Instalar un certificado").
2. Elija **Certificado de CA** › "Instalar de todos modos" › `jarvis-ca.crt`.

**iPhone / iPad**
1. Al abrir el enlace en **Safari**, acepte "Descargar perfil".
2. Ajustes › General › **VPN y gestión de dispositivos** › JARVIS (Caddy Local Authority) › Instalar.
3. Ajustes › General › Información › **Ajustes de confianza de certificados** › active Caddy Local Authority.

> El certificado raíz no es secreto: la clave privada que firma los certificados nunca sale del PC (`%APPDATA%\Caddy`). Instalarlo sólo hace que el celular confíe en `https://<ip-del-pc>`.

### 5. Entrar
Abra **`https://<ip-del-pc>`**, inicie sesión y toque el micrófono para hablarle.

### 6. IP fija (recomendado)
Si el router le cambia la IP al PC, el celular ya no lo encuentra. En el panel del router (normalmente `http://192.168.1.1` o `http://192.168.0.1`) busque **"Reserva DHCP"** o **"IP estática"** y asigne siempre la misma IP a este PC (aparece al ejecutar `.\scripts\jarvis.ps1 estado`).

---

## Seguridad: qué protege y qué no

- **Contraseñas con Argon2**: se guardan cifradas de forma irreversible; ni JARVIS puede leerlas.
- **Sesión en cookie** `HttpOnly` (el JavaScript de la página no la lee), `SameSite=Lax` (otros sitios no la usan) y `Secure` detrás de HTTPS. Vence a los 30 días.
- **5 contraseñas equivocadas** seguidas bloquean ese usuario 5 minutos.
- **El agente de voz del PC** entra con un token propio (`data/agent.token`), que nunca va a Git.
- **No protege** si alguien ya tiene acceso al PC mismo o a la carpeta `data/`.

## Resumen

| Desde | Dirección |
|---|---|
| El propio PC servidor | `http://localhost:8000` |
| Celular, tablet u otro PC de la casa | `https://<ip-del-pc>` |
| Fuera de casa | **No disponible** (decisión de privacidad). Si algún día lo quiere, la forma segura es una VPN como WireGuard o Tailscale, nunca abrir puertos en el router. |
