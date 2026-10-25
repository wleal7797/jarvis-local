"""Preferencias que se cambian desde la app (no desde .env) y deben sobrevivir reinicios.

Se guardan en `data/preferences.json` (ignorado por Git). Si existe, gana sobre `.env`.
Hoy: la voz de JARVIS y su velocidad.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path("data/preferences.json")


def load_preferences(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("preferencias ilegibles; se ignoran", extra={"error": str(exc)})
        return {}


def save_preferences(updates: dict[str, Any], path: Path = DEFAULT_PATH) -> dict[str, Any]:
    current = load_preferences(path)
    current.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current
