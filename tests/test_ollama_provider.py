"""Pruebas de OllamaProvider con un Ollama simulado (sin red)."""

import json

import httpx
import pytest

from app.services.llm import ChatMessage, LLMError, OllamaProvider

pytestmark = pytest.mark.anyio

NDJSON_REPLY = "\n".join(
    json.dumps(line)
    for line in [
        {"message": {"role": "assistant", "content": "Hola"}, "done": False},
        {"message": {"role": "assistant", "content": ", señor."}, "done": False},
        {
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "prompt_eval_count": 30,
            "eval_count": 8,
            "eval_duration": 200_000_000,  # 0,2 s → 40 tokens/s
        },
    ]
)


def provider_with(handler) -> OllamaProvider:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OllamaProvider(http, "http://ollama.test", default_model="jarvis:base")


async def collect(provider: OllamaProvider, **kwargs):
    messages = [ChatMessage(role="user", content="Hola")]
    return [chunk async for chunk in provider.chat_stream(messages, **kwargs)]


async def test_transmite_pedazos_y_estadisticas():
    received = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(json.loads(request.content))
        return httpx.Response(200, text=NDJSON_REPLY)

    chunks = await collect(provider_with(handler))

    assert "".join(c.content for c in chunks) == "Hola, señor."
    last = chunks[-1]
    assert last.done and last.tokens_in == 30 and last.tokens_out == 8
    assert last.tokens_per_second == 40.0
    assert received["model"] == "jarvis:base"
    assert received["stream"] is True
    assert received["messages"] == [{"role": "user", "content": "Hola"}]


async def test_usa_el_modelo_y_opciones_indicados():
    received = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(json.loads(request.content))
        return httpx.Response(200, text=NDJSON_REPLY)

    await collect(provider_with(handler), model="qwen3:4b", options={"temperature": 0})

    assert received["model"] == "qwen3:4b"
    assert received["options"] == {"temperature": 0}


async def test_error_http_se_convierte_en_llm_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'x' not found"})

    with pytest.raises(LLMError, match="404"):
        await collect(provider_with(handler))


async def test_sin_conexion_se_convierte_en_llm_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("rechazada", request=request)

    with pytest.raises(LLMError, match="No se pudo conectar"):
        await collect(provider_with(handler))


async def test_error_a_mitad_de_respuesta():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.dumps({"message": {"content": "Ho"}, "done": False}) + "\n"
        body += json.dumps({"error": "sin memoria en la GPU"})
        return httpx.Response(200, text=body)

    with pytest.raises(LLMError, match="sin memoria"):
        await collect(provider_with(handler))
