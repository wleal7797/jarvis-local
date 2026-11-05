"""Protocolo Odiseo: JARVIS no se conecta a la red. Nunca.

Como Odiseo atado al mástil para oír a las sirenas sin poder ir hacia ellas: JARVIS puede
recibir cualquier orden ("búscalo en internet", "conéctate", "descarga…"), pero no tiene
cómo obedecerla. Se activa al arrancar cada proceso (API, worker y agente de voz) y:

- **Bloquea en la raíz** (el módulo `socket` de Python) toda conexión que no sea a este
  mismo PC (127.0.0.1 / ::1). Ninguna librería, herramienta ni respuesta del modelo puede
  saltárselo: todas pasan por ahí.
- **Bloquea las consultas DNS** de nombres de internet (ni siquiera pregunta dónde está
  `google.com`).
- **Anota cada intento** en `logs/odiseo.log` (fecha, destino y quién lo intentó).
- Pone en modo "sin conexión" a las librerías que descargan modelos (Hugging Face).

Recibir conexiones (el navegador del celular hacia Caddy, Caddy hacia la API) no se toca:
eso es la red de la casa entrando a JARVIS, no JARVIS saliendo.

No hay ningún endpoint, herramienta ni orden por chat para apagarlo. Sólo quien tiene el PC
puede, editando `.env` (`ODISEO=false`) y reiniciando, y JARVIS lo avisa en el registro.
"""

import asyncio
import asyncio.proactor_events
import asyncio.selector_events
import ipaddress
import logging
import os
import socket
import sysconfig
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("odiseo")

LOG_FILE = Path("logs/odiseo.log")
_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_active = False

# Librerías que, sin esto, intentan descargar o "revisar actualizaciones".
OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
}


class OdiseoBlocked(ConnectionRefusedError):
    """Intento de conexión hacia fuera del PC (bloqueado por el Protocolo Odiseo)."""


def is_local(host: object) -> bool:
    """¿Es este mismo PC? (sólo loopback; ni siquiera otros equipos de la casa)."""
    if not isinstance(host, str):
        return False
    if host.lower() in ("localhost", "localhost.localdomain", ""):
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


_STDLIB = os.path.normcase(sysconfig.get_paths()["stdlib"])


def _caller() -> str:
    """Quién intentó conectarse: el código de JARVIS más cercano (no Python ni librerías)."""
    here = os.path.normcase(__file__)
    frames = [f for f in traceback.extract_stack() if os.path.normcase(f.filename) != here]
    ours = [
        f
        for f in frames
        if "site-packages" not in f.filename
        and not os.path.normcase(f.filename).startswith(_STDLIB)
    ]
    frame = (ours or frames or [None])[-1]
    return f"{Path(frame.filename).name}:{frame.lineno}" if frame else "?"


def _record(what: str) -> None:
    caller = _caller()
    line = f"{datetime.now().isoformat(timespec='seconds')} BLOQUEADO {what} (desde {caller})"
    logger.warning("Odiseo bloqueó una conexión", extra={"destino": what, "desde": caller})
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
    except OSError:
        pass


def _host_of(address: object) -> object:
    return address[0] if isinstance(address, tuple) and address else address


def _guarded_connect(self: socket.socket, address: object) -> None:
    if self.family in (socket.AF_INET, socket.AF_INET6) and not is_local(_host_of(address)):
        _record(f"conexión a {_host_of(address)}")
        raise OdiseoBlocked(f"Protocolo Odiseo: JARVIS no se conecta a {_host_of(address)}")
    return _ORIGINAL_CONNECT(self, address)


def _guarded_connect_ex(self: socket.socket, address: object) -> int:
    if self.family in (socket.AF_INET, socket.AF_INET6) and not is_local(_host_of(address)):
        _record(f"conexión a {_host_of(address)}")
        raise OdiseoBlocked(f"Protocolo Odiseo: JARVIS no se conecta a {_host_of(address)}")
    return _ORIGINAL_CONNECT_EX(self, address)


def _guarded_getaddrinfo(host, *args, **kwargs):
    name = host.decode() if isinstance(host, bytes) else host
    if name is not None and not is_local(name):
        try:
            ipaddress.ip_address(str(name).split("%")[0])
        except ValueError:  # un nombre de internet: ni siquiera se pregunta dónde está
            _record(f"búsqueda DNS de {name}")
            raise OdiseoBlocked(f"Protocolo Odiseo: JARVIS no busca {name}") from None
    return _ORIGINAL_GETADDRINFO(host, *args, **kwargs)


# En Windows, las conexiones asíncronas (httpx, websockets) usan ConnectEx a través del
# bucle de eventos y NO pasan por socket.connect: también se vigila esa puerta.
_ASYNC_LOOPS = (
    asyncio.selector_events.BaseSelectorEventLoop,
    asyncio.proactor_events.BaseProactorEventLoop,
)
_ORIGINAL_SOCK_CONNECT = {loop: loop.sock_connect for loop in _ASYNC_LOOPS}


def _guard_async(original):
    async def sock_connect(self, sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not is_local(_host_of(address)):
            _record(f"conexión a {_host_of(address)}")
            raise OdiseoBlocked(f"Protocolo Odiseo: JARVIS no se conecta a {_host_of(address)}")
        return await original(self, sock, address)

    sock_connect.odiseo = True  # type: ignore[attr-defined]
    return sock_connect


def activate() -> Callable[[], None]:
    """Activa el protocolo en este proceso. Devuelve cómo deshacerlo (sólo para pruebas)."""
    global _active
    os.environ.update(OFFLINE_ENV)
    socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = _guarded_getaddrinfo  # type: ignore[assignment]
    for loop, original in _ORIGINAL_SOCK_CONNECT.items():
        loop.sock_connect = _guard_async(original)  # type: ignore[method-assign]
    if not _active:
        logger.info("Protocolo Odiseo activo: sin conexiones hacia fuera de este PC")
    _active = True

    def undo() -> None:
        global _active
        socket.socket.connect = _ORIGINAL_CONNECT  # type: ignore[method-assign]
        socket.socket.connect_ex = _ORIGINAL_CONNECT_EX  # type: ignore[method-assign]
        socket.getaddrinfo = _ORIGINAL_GETADDRINFO
        for loop, original in _ORIGINAL_SOCK_CONNECT.items():
            loop.sock_connect = original  # type: ignore[method-assign]
        _active = False

    return undo


def is_active() -> bool:
    return _active and socket.socket.connect is _guarded_connect


def apply(enabled: bool) -> None:
    """Lo llama cada proceso al arrancar, según `ODISEO` en la configuración."""
    if enabled:
        activate()
    else:
        logger.warning(
            "PROTOCOLO ODISEO APAGADO (ODISEO=false en .env): JARVIS podría conectarse a la red"
        )
