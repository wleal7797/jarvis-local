"""Pruebas del endpoint /health.

Ollama se simula con `httpx.MockTransport` y la base de datos con una función falsa,
así estas pruebas no necesitan nada instalado.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db_probe, get_http_client
from app.main import create_app


async def db_up() -> str:
    return "0.8.7"


async def db_down() -> str:
    raise ConnectionRefusedError("sin conexión")


def ollama_up(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/api/version"
    return httpx.Response(200, json={"version": "0.40.11"})


def ollama_down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("conexión rechazada", request=request)


def make_client(ollama_handler=ollama_up, db_probe=db_up) -> TestClient:
    app = create_app()
    fake_http = httpx.AsyncClient(transport=httpx.MockTransport(ollama_handler))
    app.dependency_overrides[get_http_client] = lambda: fake_http
    app.dependency_overrides[get_db_probe] = lambda: db_probe
    return TestClient(app)


def get_health(**kwargs) -> dict:
    with make_client(**kwargs) as client:
        response = client.get("/health")
    assert response.status_code == 200
    return response.json()


def test_api_root_responde():
    with make_client() as client:
        response = client.get("/api")
    assert response.status_code == 200
    assert response.json()["health"] == "/health"


def test_health_ok_cuando_todo_responde():
    body = get_health()
    assert body["status"] == "ok"
    assert body["dependencies"]["ollama"] == {
        "status": "up",
        "detail": "Ollama 0.40.11",
        "latency_ms": body["dependencies"]["ollama"]["latency_ms"],
    }
    assert body["dependencies"]["database"]["detail"] == "PostgreSQL + pgvector 0.8.7"


def test_health_degradado_cuando_ollama_no_responde():
    body = get_health(ollama_handler=ollama_down)
    assert body["status"] == "degraded"
    assert body["dependencies"]["ollama"]["status"] == "down"
    assert body["dependencies"]["database"]["status"] == "up"


def test_health_degradado_cuando_la_base_no_responde():
    body = get_health(db_probe=db_down)
    assert body["status"] == "degraded"
    assert body["dependencies"]["database"]["status"] == "down"
    assert body["dependencies"]["ollama"]["status"] == "up"


@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
def test_documentacion_disponible(path):
    with make_client() as client:
        assert client.get(path).status_code == 200
