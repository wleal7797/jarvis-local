"""Implementación de `LLMProvider` con la API HTTP de Ollama.

Ollama responde en NDJSON: una línea JSON por cada pedazo de texto generado.
Documentación: https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-chat-completion
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.services.llm.base import ChatChunk, ChatMessage, LLMError

logger = logging.getLogger(__name__)


class OllamaProvider:
    def __init__(self, http: httpx.AsyncClient, base_url: str, default_model: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[ChatChunk]:
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }
        if options:
            payload["options"] = options

        try:
            async with self._http.stream(
                "POST", f"{self._base_url}/api/chat", json=payload
            ) as response:
                if response.status_code != 200:
                    detail = (await response.aread()).decode(errors="replace")
                    raise LLMError(f"Ollama respondió {response.status_code}: {detail}")
                async for line in response.aiter_lines():
                    if line.strip():
                        yield _parse_line(line)
        except httpx.HTTPError as exc:
            logger.error("Fallo al hablar con Ollama", extra={"error": str(exc)})
            raise LLMError("No se pudo conectar con Ollama") from exc


def _parse_line(line: str) -> ChatChunk:
    data = json.loads(line)
    if "error" in data:
        raise LLMError(f"Ollama: {data['error']}")
    content = data.get("message", {}).get("content", "")
    if not data.get("done"):
        return ChatChunk(content=content)

    tokens_out = data.get("eval_count")
    eval_ns = data.get("eval_duration")
    speed = round(tokens_out / (eval_ns / 1e9), 1) if tokens_out and eval_ns else None
    return ChatChunk(
        content=content,
        done=True,
        tokens_in=data.get("prompt_eval_count"),
        tokens_out=tokens_out,
        tokens_per_second=speed,
    )
