"""Piezas falsas para las pruebas: un modelo de lenguaje que responde lo que le digamos."""

import hashlib
import math
import re
import unicodedata
from collections.abc import AsyncIterator
from typing import Any

from app.models import EMBEDDING_DIM
from app.services.embedding_service import EmbeddingError
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


def _words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return [w[:5] for w in re.findall(r"[a-z0-9]+", plain) if len(w) > 2]


class FakeEmbedder:
    """Vectores de "bolsa de palabras": textos que comparten palabras se parecen.

    No entiende sinónimos como bge-m3, pero es determinista y no necesita Ollama.
    """

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.fail:
            raise EmbeddingError("Ollama apagado")
        return [self._vector(t) for t in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIM
        for word in _words(text):
            slot = int(hashlib.md5(word.encode()).hexdigest(), 16) % EMBEDDING_DIM
            vector[slot] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]
