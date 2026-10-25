"""Convierte texto en vectores de significado con `bge-m3` (Ollama).

Un *embedding* es una lista de 1024 números que representa el significado de un texto.
Textos con significado parecido producen vectores que apuntan en direcciones parecidas,
y eso es lo que compara pgvector al buscar.

Corre en la CPU (`num_gpu: 0`) para no quitarle memoria de video al modelo de chat.
"""

import logging
from typing import Protocol

import httpx

from app.models import EMBEDDING_DIM

logger = logging.getLogger(__name__)

# Cuántos textos se envían a Ollama en cada petición al indexar.
BATCH_SIZE = 16


class EmbeddingError(RuntimeError):
    pass


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str,
        model: str,
        *,
        use_gpu: bool = False,
        threads: int | None = None,
        keep_alive: str | None = None,
    ) -> None:
        self._http = http
        self._url = base_url.rstrip("/") + "/api/embed"
        self._model = model
        self._options: dict = {} if use_gpu else {"num_gpu": 0}
        if threads and not use_gpu:
            self._options["num_thread"] = threads
        self._keep_alive = keep_alive

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            vectors.extend(await self._embed_batch(texts[start : start + BATCH_SIZE]))
        return vectors

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        payload: dict = {"model": self._model, "input": batch, "options": self._options}
        if self._keep_alive:
            payload["keep_alive"] = self._keep_alive
        try:
            response = await self._http.post(self._url, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Ollama no generó embeddings", extra={"error": str(exc)})
            raise EmbeddingError("No se pudieron generar los embeddings") from exc
        vectors = response.json().get("embeddings", [])
        if len(vectors) != len(batch) or any(len(v) != EMBEDDING_DIM for v in vectors):
            raise EmbeddingError(
                f"Se esperaban {len(batch)} vectores de {EMBEDDING_DIM} dimensiones"
            )
        return vectors
