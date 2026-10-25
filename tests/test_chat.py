"""Pruebas del chat: servicio y endpoints, con base de datos real y modelo falso."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.dependencies import get_embedder, get_llm, get_session_factory
from app.main import create_app
from app.models import Message, ModelVersion, User
from app.services.chat_service import ChatService, ConversationNotFoundError
from tests.fakes import FakeEmbedder, FakeLLM

pytestmark = [pytest.mark.anyio, pytest.mark.db]

MODEL = "jarvis:base"


@pytest.fixture
async def user(session: AsyncSession) -> User:
    owner = User(username="dueno", display_name="Dueño", password_hash="!", role="owner")
    session.add_all([owner, ModelVersion(ollama_tag=MODEL, base_model="Qwen3", kind="base")])
    await session.commit()
    return owner


async def run(service: ChatService, user: User, text: str, conversation_id=None) -> list[dict]:
    return [event async for event in service.answer(user.id, text, conversation_id)]


# ---------- Servicio ----------


async def test_guarda_pregunta_y_respuesta(session_factory: async_sessionmaker, user: User):
    llm = FakeLLM("Buenas tardes, a su servicio.")
    events = await run(ChatService(session_factory, llm, MODEL), user, "Hola JARVIS")

    assert [e["type"] for e in events][0] == "start"
    assert events[-1]["type"] == "end"
    text = "".join(e["content"] for e in events if e["type"] == "token")
    assert text.strip() == "Buenas tardes, a su servicio."

    async with session_factory() as session:
        stored = (await session.scalars(select(Message).order_by(Message.id))).all()
    assert [(m.role, m.content) for m in stored] == [
        ("user", "Hola JARVIS"),
        ("assistant", "Buenas tardes, a su servicio."),
    ]
    assert stored[1].tokens_in == 42
    assert stored[1].model_version_id is not None
    assert stored[1].latency_ms is not None


async def test_el_historial_llega_al_modelo(session_factory: async_sessionmaker, user: User):
    llm = FakeLLM("Entendido.")
    service = ChatService(session_factory, llm, MODEL)

    first = await run(service, user, "Me llamo Ana")
    conversation_id = first[0]["conversation_id"]
    await run(service, user, "¿Cómo me llamo?", conversation_id)

    sent = [(m.role, m.content) for m in llm.calls[-1]]
    assert sent == [
        ("user", "Me llamo Ana"),
        ("assistant", "Entendido."),
        ("user", "¿Cómo me llamo?"),
    ]


async def test_conversacion_ajena_no_se_puede_usar(
    session_factory: async_sessionmaker, user: User, session: AsyncSession
):
    other = User(username="otro", display_name="Otro", password_hash="!", role="member")
    session.add(other)
    await session.commit()
    service = ChatService(session_factory, FakeLLM(), MODEL)
    conversation_id = (await run(service, user, "Secreto"))[0]["conversation_id"]

    with pytest.raises(ConversationNotFoundError):
        await service.ensure_conversation(other.id, conversation_id)


async def test_si_el_modelo_falla_avisa_y_no_guarda_respuesta(
    session_factory: async_sessionmaker, user: User
):
    events = await run(ChatService(session_factory, FakeLLM(fail=True), MODEL), user, "Hola")

    assert events[-1]["type"] == "error"
    async with session_factory() as session:
        roles = (await session.scalars(select(Message.role))).all()
    assert roles == ["user"]


# ---------- Endpoints ----------


@pytest.fixture
async def app_session_factory(test_db_url: str) -> AsyncIterator[async_sessionmaker]:
    """Conexiones reales (una por petición, como en producción) a la base de pruebas.

    Al compartir una sola conexión, FastAPI cerraría la sesión de una petición mientras
    empieza la siguiente. Por eso aquí cada sesión tiene su conexión y al final se vacían
    las tablas.
    """
    engine = create_async_engine(test_db_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                User(username="dueno", display_name="Dueño", password_hash="!", role="owner"),
                ModelVersion(ollama_tag=MODEL, base_model="Qwen3", kind="base"),
            ]
        )
        await session.commit()
    yield factory
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE users, model_versions RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest.fixture
def client(app_session_factory: async_sessionmaker) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: app_session_factory
    app.dependency_overrides[get_llm] = lambda: FakeLLM("Con gusto.")
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_post_chat_transmite_ndjson(client: httpx.AsyncClient):
    async with client:
        response = await client.post("/api/chat", json={"message": "Hola"})
        events = [json.loads(line) for line in response.text.splitlines()]

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        assert events[0]["type"] == "start" and events[-1]["type"] == "end"

        conversation_id = events[0]["conversation_id"]
        conversations = (await client.get("/api/conversations")).json()
        assert conversations[0]["id"] == conversation_id
        assert conversations[0]["title"] == "Hola"

        messages = (await client.get(f"/api/conversations/{conversation_id}/messages")).json()
        assert [m["role"] for m in messages] == ["user", "assistant"]


async def test_conversacion_inexistente_da_404(client: httpx.AsyncClient):
    async with client:
        response = await client.post("/api/chat", json={"message": "Hola", "conversation_id": 999})
        assert response.status_code == 404
        assert (await client.get("/api/conversations/999/messages")).status_code == 404


async def test_borrar_conversacion(client: httpx.AsyncClient):
    async with client:
        response = await client.post("/api/chat", json={"message": "Borrar esto"})
        conversation_id = json.loads(response.text.splitlines()[0])["conversation_id"]

        assert (await client.delete(f"/api/conversations/{conversation_id}")).status_code == 204
        assert (
            await client.get(f"/api/conversations/{conversation_id}/messages")
        ).status_code == 404


async def test_mensaje_vacio_es_rechazado(client: httpx.AsyncClient):
    async with client:
        assert (await client.post("/api/chat", json={"message": ""})).status_code == 422
