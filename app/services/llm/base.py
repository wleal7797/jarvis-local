"""Interfaz común para cualquier modelo de lenguaje.

El resto de la app sólo conoce `LLMProvider`. Hoy lo implementa Ollama, pero se podría
cambiar por otro servidor local (llama.cpp, vLLM…) sin tocar servicios ni controladores.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class ChatChunk:
    """Un pedazo de la respuesta mientras se genera.

    El último pedazo trae `done=True` y las estadísticas de la generación.
    """

    content: str = ""
    done: bool = False
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_per_second: float | None = None


class LLMError(RuntimeError):
    """El modelo no respondió o respondió con un error."""


class LLMProvider(Protocol):
    def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[ChatChunk]:
        """Genera la respuesta pedazo a pedazo (streaming)."""
        ...

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        options: dict[str, Any] | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        """Respuesta completa de una vez. Con `json_schema`, el modelo sólo puede
        responder un JSON con esa forma (útil para tareas internas)."""
        ...

    async def warm(self, keep_alive: str = "10m", prefill: bool = False) -> None:
        """Deja el modelo cargado y listo para responder sin esperar."""
        ...
