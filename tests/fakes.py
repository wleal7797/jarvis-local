"""Piezas falsas para las pruebas: un modelo de lenguaje que responde lo que le digamos."""

from collections.abc import AsyncIterator
from typing import Any

from app.services.llm import ChatChunk, ChatMessage, LLMError


class FakeLLM:
    """Responde siempre `reply`, pedazo a pedazo, y recuerda lo que recibió."""

    def __init__(self, reply: str = "Hola, soy JARVIS.", fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls: list[list[ChatMessage]] = []

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[ChatChunk]:
        self.calls.append(messages)
        if self.fail:
            raise LLMError("Ollama apagado")
        for word in self.reply.split(" "):
            yield ChatChunk(content=word + " ")
        yield ChatChunk(
            done=True, tokens_in=42, tokens_out=len(self.reply.split()), tokens_per_second=40.0
        )
