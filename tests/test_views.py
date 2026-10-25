"""Pruebas de la vista web y del WebSocket de chat (sin base de datos ni GPU)."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_chat_service, get_current_user, get_tts
from app.main import create_app
from app.services.chat_service import ConversationNotFoundError


class StubChatService:
    """Responde con eventos fijos y recuerda lo que recibió."""

    def __init__(self) -> None:
        self.received: list[tuple[int, str, int | None]] = []

    async def ensure_conversation(self, user_id: int, conversation_id: int) -> None:
        if conversation_id != 7:
            raise ConversationNotFoundError(conversation_id)

    async def answer(self, user_id: int, text: str, conversation_id: int | None = None):
        self.received.append((user_id, text, conversation_id))
        yield {"type": "start", "conversation_id": conversation_id or 7, "message_id": 1}
        yield {"type": "token", "content": "Hola, "}
        yield {"type": "token", "content": "a su servicio."}
        yield {"type": "end", "message_id": 2, "latency_ms": 900, "tokens_per_second": 38.5}


@pytest.fixture
def stub() -> StubChatService:
    return StubChatService()


@pytest.fixture
def client(stub: StubChatService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[get_chat_service] = lambda: stub
    app.dependency_overrides[get_tts] = lambda: None  # estas pruebas no piden voz
    return TestClient(app)


def receive_until_end(ws) -> list[dict]:
    events = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event["type"] in ("end", "error"):
            return events


# ---------- Páginas y archivos estáticos ----------


def test_pagina_de_chat(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "<title>JARVIS</title>" in html
    assert "/static/js/chat.js" in html
    assert 'id="composer"' in html


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/static/css/app.css", "text/css"),
        ("/static/js/chat.js", "javascript"),
        ("/static/js/markdown.js", "javascript"),
        ("/static/img/jarvis.svg", "image/svg+xml"),
        ("/favicon.ico", "image/svg+xml"),
    ],
)
def test_archivos_estaticos(client: TestClient, path: str, content_type: str):
    response = client.get(path)
    assert response.status_code == 200
    assert content_type in response.headers["content-type"]


def test_la_pagina_no_carga_nada_de_internet(client: TestClient):
    """Privacidad: todo se sirve desde este PC, sin CDN ni fuentes externas."""
    html = client.get("/").text
    assert "http://" not in html and "https://" not in html


# ---------- WebSocket ----------


def test_websocket_transmite_la_respuesta(client: TestClient, stub: StubChatService):
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hola JARVIS", "conversation_id": None})
        events = receive_until_end(ws)

    assert [e["type"] for e in events] == ["start", "token", "token", "end"]
    assert "".join(e["content"] for e in events if e["type"] == "token") == "Hola, a su servicio."
    assert stub.received == [(1, "Hola JARVIS", None)]


def test_websocket_permite_varios_mensajes_en_la_misma_conexion(
    client: TestClient, stub: StubChatService
):
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Uno"})
        receive_until_end(ws)
        ws.send_json({"message": "Dos", "conversation_id": 7})
        receive_until_end(ws)

    assert [text for _, text, _ in stub.received] == ["Uno", "Dos"]


def test_websocket_rechaza_mensaje_invalido(client: TestClient, stub: StubChatService):
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_text('{"message": ""}')
        assert ws.receive_json() == {"type": "error", "message": "Mensaje inválido."}
        ws.send_text("esto no es JSON")
        assert ws.receive_json()["type"] == "error"
    assert stub.received == []


def test_websocket_conversacion_ajena(client: TestClient, stub: StubChatService):
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hola", "conversation_id": 999})
        assert ws.receive_json() == {"type": "error", "message": "Conversación no encontrada"}
    assert stub.received == []
