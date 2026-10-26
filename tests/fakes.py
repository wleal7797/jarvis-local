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

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        options: dict[str, Any] | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        self.calls.append(messages)
        if self.fail:
            raise LLMError("Ollama apagado")
        return self.reply

    async def warm(self, keep_alive: str = "10m", prefill: bool = False) -> None:
        self.warmed = keep_alive
        self.prefilled = prefill


class FakeMemory:
    """Memoria que no recuerda nada (o lo que le digamos)."""

    def __init__(self, facts: list[str] | None = None, learned=None) -> None:
        self.facts = facts or []
        self.learned = learned or []
        self.learn_calls: list[tuple[int, int]] = []

    async def facts_for_prompt(self, user_id: int) -> list[str]:
        return self.facts

    async def all_for(self, user_id: int) -> list:
        return []

    async def relevant(self, user_id: int, text: str) -> list[str]:
        return self.facts[:3]

    async def learn(self, user_id: int, reply_message_id: int):
        self.learn_calls.append((user_id, reply_message_id))
        return self.learned


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


def owner_user():
    """El dueño, para las pruebas que no prueban el inicio de sesión."""
    from types import SimpleNamespace

    return SimpleNamespace(
        id=1, username="dueno", display_name="Dueño", role="owner", is_active=True
    )


def as_owner(app) -> None:
    """Hace que todas las peticiones de `app` entren como el dueño."""
    from app.core.dependencies import get_current_user, get_optional_user

    app.dependency_overrides[get_current_user] = owner_user
    app.dependency_overrides[get_optional_user] = owner_user
