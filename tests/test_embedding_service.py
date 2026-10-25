"""Pruebas de OllamaEmbedder con un Ollama simulado."""

import json

import httpx
import pytest

from app.models import EMBEDDING_DIM
from app.services.embedding_service import BATCH_SIZE, EmbeddingError, OllamaEmbedder

pytestmark = pytest.mark.anyio


def embedder(handler, use_gpu: bool = False) -> OllamaEmbedder:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OllamaEmbedder(http, "http://ollama.test", "bge-m3", use_gpu=use_gpu)


def ok_handler(requests: list):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200, json={"embeddings": [[0.1] * EMBEDDING_DIM for _ in body["input"]]}
        )

    return handler


async def test_pide_bge_m3_en_cpu_por_defecto():
    requests: list = []
    vectors = await embedder(ok_handler(requests)).embed(["hola", "mundo"])

    assert len(vectors) == 2 and len(vectors[0]) == EMBEDDING_DIM
    assert requests[0]["model"] == "bge-m3"
    assert requests[0]["options"] == {"num_gpu": 0}


async def test_en_gpu_no_limita_capas():
    requests: list = []
    await embedder(ok_handler(requests), use_gpu=True).embed(["hola"])
    assert requests[0]["options"] == {}


async def test_envia_por_lotes():
    requests: list = []
    texts = [f"texto {i}" for i in range(BATCH_SIZE * 2 + 3)]
    vectors = await embedder(ok_handler(requests)).embed(texts)

    assert len(vectors) == len(texts)
    assert [len(r["input"]) for r in requests] == [BATCH_SIZE, BATCH_SIZE, 3]


async def test_dimension_incorrecta_es_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1] * 768]})

    with pytest.raises(EmbeddingError, match="1024"):
        await embedder(handler).embed(["hola"])


async def test_ollama_apagado_es_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("rechazada", request=request)

    with pytest.raises(EmbeddingError):
        await embedder(handler).embed(["hola"])
