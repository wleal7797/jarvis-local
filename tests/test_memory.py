"""Pruebas de la memoria (Etapa 10) y de las calificaciones 👍 / 👎."""

import json
from datetime import datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.dependencies import get_embedder, get_llm, get_session_factory
from app.main import create_app
from app.models import Message, ModelVersion, TrainingDataset, TrainingExample, User
from app.services.chat_service import ChatService
from app.services.memory_service import (
    MemoryNotFoundError,
    MemoryService,
    _parse,
    _tidy,
    grounded,
    is_personal_statement,
    worth_checking,
)
from app.services.prompt_builder import asks_time, build_messages, fit_memories
from app.services.training_service import (
    CORRECTIONS_DATASET,
    MessageNotRatableError,
    TrainingService,
)
from tests.fakes import FakeEmbedder, FakeLLM, FakeMemory

pytestmark = pytest.mark.anyio

MODEL = "jarvis:base"
NOW = datetime(2026, 10, 26, 20, 5)

# ---------- Sin base de datos ----------


@pytest.mark.parametrize(
    ("text", "check"),
    [
        ("Me gusta el café sin azúcar", True),
        ("Mi hija se llama Sofía", True),
        ("Recuerda que el lunes viene el plomero", True),
        ("¿Me recuerdas qué tengo que comprar?", True),  # pide recordar: se revisa
        ("¿Cuál es mi color favorito?", False),  # pregunta
        ("Hola Jarvis", False),  # muy corta
        ("Pon música tranquila", False),  # orden sin nada personal
    ],
)
def test_filtro_rapido_antes_de_usar_el_modelo(text: str, check: bool):
    assert worth_checking(text) is check


def test_lo_personal_no_busca_documentos():
    assert is_personal_statement("Mi perro se llama Toby")
    assert not is_personal_statement("¿Cómo se llama mi perro?")


@pytest.mark.parametrize(
    ("fact", "said", "ok"),
    [
        ("Toby es un perro labrador.", "Mi perro se llama Toby y es un labrador.", True),
        ("Su hija cumple años el 3 de marzo.", "Mi hija cumple años el 3 de marzo", True),
        ("Debe comprar leche el 27 de octubre.", "Soy alérgico a las nueces.", False),
        ("Se llama Andrés.", "Mi perro se llama Toby.", False),  # "llama" no basta
    ],
)
def test_solo_guarda_lo_que_dijo_esa_frase(fact: str, said: str, ok: bool):
    assert grounded(fact, said) is ok


def test_ordena_el_texto_del_recuerdo():
    assert _tidy("soy alérgico a las nueces") == "Es alérgico a las nueces."
    assert _tidy("mi esposa se llama Laura") == "Su esposa se llama Laura."
    assert _tidy("  Le   gusta el té.  ") == "Le gusta el té."


def test_lee_el_json_del_modelo_con_cuidado():
    raw = json.dumps(
        {
            "datos": [
                {"dato": "Se llama Andrés.", "importancia": 9},
                {"dato": "Mañana es martes 27 de octubre.", "importancia": 3},  # no es un dato
                {"dato": "ok", "importancia": 3},  # muy corto
                {"dato": "Está un poco cansado hoy.", "importancia": 1},  # pasajero
            ]
        }
    )
    assert _parse(raw) == [("Se llama Andrés.", 5)]
    assert _parse("esto no es json") == []
    assert _parse('{"datos": "mal"}') == []


def test_recuerdos_y_fecha_van_primero_y_la_hora_solo_si_la_piden():
    messages = build_messages([], "¿Qué hora es?", memories=["Se llama Ana."], now=NOW)
    assert messages[0].content.startswith("Hoy es lunes 26 de octubre de 2026.")
    assert "- Se llama Ana." in messages[0].content
    assert messages[1].role == "assistant"
    assert messages[-1].content.endswith("(Según el reloj de este computador, son las 8:05 p. m.)")

    plain = build_messages([], "Me gusta el té", now=NOW)
    assert plain[-1].content == "Me gusta el té"  # sin reloj: el modelo lo repetiría
    assert asks_time("¿Qué día es hoy?") and not asks_time("¿Cómo estás?")


def test_con_documentos_lo_que_sabe_va_junto_a_la_pregunta():
    from types import SimpleNamespace

    chunk = SimpleNamespace(title="Casa", section=None, content="El wifi es Casa123.")
    messages = build_messages([], "¿En qué trabajo?", [chunk], known=["Es ingeniero."])
    last = messages[-1].content
    assert last.index("- Es ingeniero.") < last.index("[1] Casa") < last.index("Pregunta:")


def test_los_recuerdos_respetan_su_espacio():
    facts = [f"Dato número {i} con algo de texto para ocupar espacio." for i in range(100)]
    kept = fit_memories(facts, budget=100)
    assert 0 < len(kept) < 100 and kept == facts[: len(kept)]


# ---------- Con base de datos ----------


@pytest.fixture
async def user(session: AsyncSession) -> User:
    owner = User(username="dueno", display_name="Dueño", password_hash="!", role="owner")
    session.add_all([owner, ModelVersion(ollama_tag=MODEL, base_model="Qwen3", kind="base")])
    await session.commit()
    return owner


def memory_service(factory, reply: str = '{"datos": []}') -> MemoryService:
    return MemoryService(factory, FakeLLM(reply), FakeEmbedder(), MODEL, clock=lambda: NOW)


async def chat(service: ChatService, user: User, text: str, conversation_id=None):
    events = [e async for e in service.answer(user.id, text, conversation_id)]
    return events[0]["conversation_id"], events[-1]["message_id"]


@pytest.mark.db
async def test_agrega_corrige_y_borra_recuerdos(session_factory, user: User):
    memory = memory_service(session_factory)
    first = await memory.add(user.id, "le gusta el café sin azúcar", importance=3)
    assert first.content == "Le gusta el café sin azúcar." and not first.updated

    # Casi igual: reemplaza en vez de duplicar.
    again = await memory.add(user.id, "Le gusta mucho el café sin azúcar.", importance=5)
    assert again.updated and again.memory_id == first.memory_id
    stored = await memory.all_for(user.id)
    assert [(m.content, m.importance) for m in stored] == [
        ("Le gusta mucho el café sin azúcar.", 5)
    ]

    await memory.add(user.id, "Su hija se llama Sofía.", importance=5)
    assert len(await memory.all_for(user.id)) == 2
    assert "Su hija se llama Sofía." in await memory.facts_for_prompt(user.id)

    fixed = await memory.update(user.id, first.memory_id, "Le gusta el té verde.", None)
    assert fixed.content == "Le gusta el té verde."
    await memory.delete(user.id, first.memory_id)
    with pytest.raises(MemoryNotFoundError):
        await memory.delete(user.id, first.memory_id)
    with pytest.raises(MemoryNotFoundError):  # los recuerdos de otro usuario no se tocan
        await memory.update(user.id + 1, fixed.id, "x x x", None)


@pytest.mark.db
async def test_aprende_de_la_conversacion_solo_lo_que_dijo(session_factory, user: User):
    service = ChatService(session_factory, FakeLLM("Entendido."), MODEL)
    _, reply_id = await chat(service, user, "Mi perro se llama Toby y es un labrador.")
    extraction = json.dumps(
        {
            "datos": [
                {"dato": "Su perro se llama Toby.", "importancia": 3},
                {"dato": "Debe comprar leche el martes.", "importancia": 3},  # inventado
            ]
        }
    )
    memory = memory_service(session_factory, extraction)
    learned = await memory.learn(user.id, reply_id)

    assert [item.content for item in learned] == ["Su perro se llama Toby."]
    stored = await memory.all_for(user.id)
    assert stored[0].source_message_id is not None  # se sabe de qué frase salió
    prompt = memory._llm.calls[-1][-1].content
    assert "Tarea interna" in prompt and "lunes 26 de octubre de 2026" in prompt


@pytest.mark.db
async def test_preguntas_y_ordenes_no_gastan_el_modelo(session_factory, user: User):
    service = ChatService(session_factory, FakeLLM("París."), MODEL)
    _, reply_id = await chat(service, user, "¿Cuál es la capital de Francia?")
    memory = memory_service(session_factory, '{"datos": [{"dato": "x", "importancia": 1}]}')
    assert await memory.learn(user.id, reply_id) == []
    assert memory._llm.calls == []  # ni siquiera le preguntó al modelo


@pytest.mark.db
async def test_revisar_la_frase_no_estropea_la_cache_de_la_siguiente_pregunta(
    session_factory, user: User
):
    """La revisión usa el mismo principio de mensaje que la siguiente pregunta."""
    chat_llm = FakeLLM("Entendido.")
    service = ChatService(session_factory, chat_llm, MODEL, clock=lambda: NOW)
    conversation_id, reply_id = await chat(service, user, "Me gusta el té verde por la tarde.")
    memory = memory_service(session_factory)  # no aprende nada: los recuerdos no cambian
    await memory.learn(user.id, reply_id)
    await chat(service, user, "Gracias", conversation_id)

    review = memory._llm.calls[-1]
    next_question = chat_llm.calls[-1]
    assert review[:-1] == next_question[:-1]


@pytest.mark.db
async def test_el_chat_le_da_los_recuerdos_al_modelo(session_factory, user: User):
    llm = FakeLLM("Se llama Ana.")
    service = ChatService(session_factory, llm, MODEL, memory=FakeMemory(["Se llama Ana."]))
    await chat(service, user, "¿Cómo me llamo?")
    assert "- Se llama Ana." in llm.calls[-1][0].content


@pytest.mark.db
async def test_calificar_y_corregir_crea_un_ejemplo_de_entrenamiento(
    session_factory, user: User, session: AsyncSession
):
    service = ChatService(session_factory, FakeLLM("Bogotá tiene 2 millones."), MODEL)
    _, reply_id = await chat(service, user, "¿Cuántos habitantes tiene Bogotá?")
    training = TrainingService(session_factory)

    liked = await training.rate(user.id, reply_id, 1)
    assert liked.rating == 1 and not liked.training_example

    fixed = await training.rate(user.id, reply_id, -1, "Bogotá tiene unos 8 millones.")
    assert fixed.training_example
    again = await training.rate(user.id, reply_id, -1, "Unos 7,9 millones (2024).")
    assert again.training_example

    dataset = await session.scalar(
        select(TrainingDataset).where(TrainingDataset.name == CORRECTIONS_DATASET)
    )
    assert dataset is not None and dataset.contains_personal_data  # nunca sale a la nube
    examples = (await session.scalars(select(TrainingExample))).all()
    assert [(e.user_prompt, e.assistant_answer, e.origin) for e in examples] == [
        ("¿Cuántos habitantes tiene Bogotá?", "Unos 7,9 millones (2024).", "feedback")
    ]

    question_id = await session.scalar(select(Message.id).where(Message.role == "user"))
    with pytest.raises(MessageNotRatableError):  # sólo se califican respuestas de JARVIS
        await training.rate(user.id, question_id, 1)


# ---------- Endpoints ----------


@pytest.fixture
def client(app_session_factory: async_sessionmaker) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: app_session_factory
    app.dependency_overrides[get_llm] = lambda: FakeLLM("Con gusto.")
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.db
async def test_endpoints_de_memoria(client: httpx.AsyncClient):
    async with client:
        created = await client.post("/api/memories", json={"content": "Le gusta el té verde"})
        assert created.status_code == 201
        memory_id = created.json()["memory_id"]

        listed = (await client.get("/api/memories")).json()
        assert [m["content"] for m in listed] == ["Le gusta el té verde."]

        patched = await client.patch(f"/api/memories/{memory_id}", json={"importance": 5})
        assert patched.json()["importance"] == 5
        assert (await client.delete(f"/api/memories/{memory_id}")).status_code == 204
        assert (await client.delete(f"/api/memories/{memory_id}")).status_code == 404
        assert (await client.post("/api/memories", json={"content": "x"})).status_code == 422


@pytest.mark.db
async def test_endpoint_de_calificacion_y_el_historial_la_muestra(client: httpx.AsyncClient):
    async with client:
        response = await client.post("/api/chat", json={"message": "Hola"})
        events = [json.loads(line) for line in response.text.splitlines()]
        conversation_id, reply_id = events[0]["conversation_id"], events[-1]["message_id"]

        rated = await client.put(f"/api/messages/{reply_id}/feedback", json={"rating": -1})
        assert rated.status_code == 200 and rated.json()["rating"] == -1
        bad = await client.put(f"/api/messages/{reply_id}/feedback", json={"rating": 3})
        assert bad.status_code == 422
        missing = await client.put("/api/messages/99999/feedback", json={"rating": 1})
        assert missing.status_code == 404

        messages = (await client.get(f"/api/conversations/{conversation_id}/messages")).json()
        assert [m["rating"] for m in messages] == [None, -1]


@pytest.mark.db
async def test_la_pagina_de_memoria(client: httpx.AsyncClient):
    async with client:
        html = (await client.get("/memoria")).text
        assert 'id="memories"' in html and "/static/js/memory.js" in html
        assert 'href="/memoria"' in (await client.get("/")).text


@pytest.mark.db
async def test_por_voz_lo_que_ya_sabe_no_busca_documentos(session_factory, user: User):
    searched: list[str] = []

    class SpyRetriever:
        async def search(self, query, owner_user_id=None):
            searched.append(query)
            return []

    service = ChatService(
        session_factory,
        FakeLLM("Se llama Rocky."),
        MODEL,
        lambda s: SpyRetriever(),
        memory=FakeMemory(["Su perro se llama Rocky."]),
    )
    question = "Jarvis, ¿cómo se llama mi perro?"
    [e async for e in service.answer(user.id, question, voice=True)]
    assert searched == []  # lo sabía: respondió sin buscar
    [e async for e in service.answer(user.id, question)]
    assert searched == [question]  # por escrito sí busca (puede haber documentos personales)
