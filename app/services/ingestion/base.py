"""Piezas comunes de la ingesta: el documento "en bruto" y la interfaz de los cargadores."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

USER_AGENT = "JARVIS-local/0.1 (asistente personal sin fines comerciales; +https://github.com/wleal7797/jarvis-local)"


@dataclass
class RawDocument:
    """Un documento ya convertido a texto (Markdown), listo para fragmentar."""

    title: str
    text: str
    uri: str | None = None
    mime_type: str = "text/markdown"
    language: str = "es"
    metadata: dict[str, Any] = field(default_factory=dict)


class LoaderError(RuntimeError):
    """No se pudo leer un origen (archivo dañado, página caída, etc.)."""


class DocumentLoader(Protocol):
    def load(self) -> AsyncIterator[RawDocument]:
        """Entrega los documentos uno por uno (así no se cargan todos en memoria)."""
        ...
