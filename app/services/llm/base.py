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
    # Etapa 13: el modelo pidió usar herramientas (sólo en mensajes del asistente).
    tool_calls: tuple[dict[str, Any], ...] = ()

    def to_ollama(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = list(self.tool_calls)
        return data


@dataclass(frozen=True)
class ToolDecision:
    """Lo que respondió el modelo cuando se le ofrecieron herramientas."""

    content: str
    tool_calls: tuple[dict[str, Any], ...] = ()


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

    async def decide(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        *,
        model: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> ToolDecision:
        """Le ofrece herramientas al modelo: responde con texto o pide usar alguna."""
        ...

    async def warm(self, keep_alive: str = "10m", prefill: bool = False) -> None:
        """Deja el modelo cargado y listo para responder sin esperar."""
        ...
