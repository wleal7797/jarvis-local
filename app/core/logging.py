"""Registro de eventos en formato JSON (una línea por evento).

Así los registros se pueden filtrar y analizar fácilmente más adelante.
"""

import contextlib
import json
import logging
import sys
from datetime import UTC, datetime

# Campos que trae todo LogRecord y que no queremos repetir como "extra".
_STANDARD_FIELDS = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Datos adicionales pasados con logger.info("...", extra={...})
        entry.update({k: v for k, v in vars(record).items() if k not in _STANDARD_FIELDS})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    # En Windows la consola puede no usar UTF-8; forzarlo para que las tildes salgan bien.
    with contextlib.suppress(AttributeError, ValueError, OSError):
        sys.stdout.reconfigure(encoding="utf-8")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Uvicorn ya registra cada petición; usamos nuestro propio middleware.
    logging.getLogger("uvicorn.access").disabled = True
    # httpx registraría cada llamada a Ollama; sólo nos interesan sus avisos.
    logging.getLogger("httpx").setLevel(logging.WARNING)
