# 02 · Acceso desde otros dispositivos de la casa

Pregunta: **si entro a `localhost` desde cualquier dispositivo de mi casa, ¿entro a la app?**

**No.** `localhost` siempre significa "este mismo aparato". Si escribes `localhost` en tu celular, el celular se busca a sí mismo, no al PC.
Los demás dispositivos deben usar la **dirección del PC dentro de tu red** (por ejemplo `192.168.1.50`).

```
              Router de la casa (192.168.1.1)
        ┌─────────────┼──────────────┬──────────────┐
   PC servidor     Celular        Tablet         Otro PC
  192.168.1.50   192.168.1.71   192.168.1.80   192.168.1.92
  JARVIS :443
        ▲              │              │              │
        └──── https://192.168.1.50  (o https://jarvis.local) ─┘
```

Todo el tráfico se queda **dentro de tu casa**. Nada pasa por internet.

---

## Lo que haremos (Etapa 10)

### 1. Escuchar en la red y no sólo en el PC
La API arranca con `--host 0.0.0.0` en lugar de `127.0.0.1`. Así acepta conexiones de otros dispositivos.

### 2. IP fija para el PC
En el panel de tu router (normalmente `192.168.1.1` o `192.168.0.1`) se crea una **reserva DHCP** para el PC. Así su IP no cambia y los demás dispositivos siempre lo encuentran.

### 3. Abrir el puerto sólo para la red privada
Regla del Firewall de Windows (PowerShell como administrador):

```powershell
New-NetFirewallRule -DisplayName "JARVIS HTTPS (LAN)" -Direction Inbound -Protocol TCP -LocalPort 443 -Profile Private -Action Allow
```

`-Profile Private` hace que la regla funcione en tu Wi‑Fi de casa (marcada como "Red privada") y no en redes públicas como un café.

### 4. HTTPS, obligatorio para usar el micrófono
Los navegadores **sólo permiten usar el micrófono** en `localhost` o en sitios con **HTTPS**.
Desde el celular, `http://192.168.1.50` **no podría escucharte**. Por eso:

- Ponemos **Caddy** delante de la API como *proxy inverso*. Caddy crea su propia autoridad certificadora local y sirve la app por HTTPS.
- Instalas el **certificado raíz de Caddy** una sola vez en cada dispositivo (celular, tablet) para que confíe en él.

### 5. Nombre fácil (opcional)
Windows anuncia su nombre en la red con mDNS. Si tu PC se llama `JARVIS-SERVER`, la app queda en `https://jarvis-server.local`. Si algún dispositivo no lo resuelve, se usa la IP.

### 6. Inicio de sesión
Como cualquier persona conectada a tu Wi‑Fi podría abrir la app, la app tendrá **usuarios con contraseña**:

| Rol | Puede |
|---|---|
| `owner` (tú) | Todo: conocimiento, entrenamiento, modelos, usuarios |
| `member` (familia) | Conversar y ver su propio historial |
| `guest` | Conversar sin acceso a datos personales |

Las contraseñas se guardan con **Argon2** (hash irreversible) y la sesión viaja en una cookie segura (`HttpOnly`, `Secure`).
Los documentos personales se marcan como `is_personal` y **sólo los ve su dueño**.

---

## Resumen

| Desde | Dirección |
|---|---|
| El propio PC servidor | `https://localhost` |
| Celular, tablet u otro PC de la casa | `https://192.168.1.50` o `https://jarvis-server.local` |
| Fuera de casa | **No disponible** (decisión de privacidad). Si algún día lo quieres, la forma segura es una VPN como WireGuard o Tailscale, nunca abrir puertos en el router. |
