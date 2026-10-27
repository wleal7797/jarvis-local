"""Claves que se crean solas la primera vez y viven en `data/` (que nunca va a Git).

- `data/secret.key`: firma las sesiones (si se borra, todos tienen que volver a entrar).
- `data/agent.token`: con él, el agente de voz del mismo PC habla con la API como el dueño.
"""

import secrets
from pathlib import Path


def load_or_create(path: str | Path, nbytes: int = 32) -> str:
    """Lee la clave del archivo; si no existe, crea una aleatoria y la guarda."""
    file = Path(path)
    if file.exists():
        value = file.read_text(encoding="utf-8").strip()
        if value:
            return value
    file.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(nbytes)
    file.write_text(value, encoding="utf-8")
    return value
