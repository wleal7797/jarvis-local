"""Pruebas del endpoint /health.

Ollama se simula con `httpx.MockTransport`, así las pruebas no necesitan nada instalado.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_http_client
from app.main import create_app


def make_client(handler) -> TestClient:
    app = create_app()
    fake_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app.dependency_overrides[get_http_client] = lambda: fake_http
    return TestClient(app)


def ollama_up(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/api/version"
    return httpx.Response(200, json={"version": "0.40.11"})


def ollama_down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("conexión rechazada", request=request)


def test_root_responde():
    with make_client(ollama_up) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.json()["health"] == "/health"


def test_health_ok_cuando_ollama_responde():
    with make_client(ollama_up) as client:
        response = client.get("/health")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["dependencies"]["ollama"]["status"] == "up"
    assert body["dependencies"]["ollama"]["detail"] == "Ollama 0.40.11"


def test_health_degradado_cuando_ollama_no_responde():
    with make_client(ollama_down) as client:
        response = client.get("/health")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "degraded"
    assert body["dependencies"]["ollama"]["status"] == "down"


@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
def test_documentacion_disponible(path):
    with make_client(ollama_up) as client:
        assert client.get(path).status_code == 200
