"""Pruebas del RAG completo: indexar, buscar, responder con fuentes (base real, modelo falso)."""

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Chunk, Document, MessageSource, ModelVersion, User
from app.services.chat_service import ChatService, cited_numbers
from app.services.knowledge_service import KnowledgeService
from app.services.prompt_builder import build_messages
from app.services.retrieval_service import (
    RetrievalService,
    RetrievalSettings,
    RetrievedChunk,
    reciprocal_rank_fusion,
)
from tests.fakes import FakeEmbedder, FakeLLM

pytestmark = pytest.mark.anyio

MANUAL = """# Manual de la casa

## Red

El router está en la sala. La contraseña del wifi está pegada debajo del router.

## Cocina

La estufa es de gas natural. El horno tarda diez minutos en calentar.

## Jardín

Las plantas se riegan los martes y los viernes por la mañana.
"""

# Umbrales para el FakeEmbedder (bolsa de palabras): más bajos que los de bge-m3.
FAKE_SETTINGS = RetrievalSettings(top_k=3, min_similarity=0.2, min_similarity_with_keywords=0.1)


@pytest.fixture
async def indexed(session: AsyncSession) -> KnowledgeService:
    service = KnowledgeService(session, FakeEmbedder())
    source = await service.get_or_create_source("manual", "Casa")
    await service.add_text(source, "Manual de la casa", MANUAL)
    await session.commit()
    return service


# ---------- Indexación ----------


@pytest.mark.db
async def test_indexar_crea_fragmentos_con_vector(indexed: KnowledgeService, session: AsyncSession):
    document = await session.scalar(select(Document))
    chunks = (await session.scalars(select(Chunk).order_by(Chunk.chunk_index))).all()

    assert document.status == "indexed" and document.indexed_at is not None
    assert [c.metadata_["section"] for c in chunks] == ["Red", "Cocina", "Jardín"]
    assert all(c.embedding is not None and c.token_count > 0 for c in chunks)


@pytest.mark.db
async def test_el_mismo_texto_no_se_indexa_dos_veces(
    indexed: KnowledgeService, session: AsyncSession
):
    source = await indexed.get_or_create_source("manual", "Casa")
    again = await indexed.add_text(source, "Copia", MANUAL)

    assert again.created is False and again.chunks == 0
    assert await session.scalar(select(func.count(Document.id))) == 1


@pytest.mark.db
async def test_si_fallan_los_embeddings_el_documento_queda_con_error(session: AsyncSession):
    service = KnowledgeService(session, FakeEmbedder(fail=True))
    source = await service.get_or_create_source("manual", "Casa")
    with pytest.raises(Exception, match="apagado"):
        await service.add_text(source, "Doc", "Algún texto")
    document = await session.scalar(select(Document))
    assert document.status == "error"


# ---------- Búsqueda ----------


@pytest.mark.db
async def test_busqueda_encuentra_la_seccion_correcta(indexed, session: AsyncSession):
    retrieval = RetrievalService(session, FakeEmbedder(), FAKE_SETTINGS)
    results = await retrieval.search("¿Qué días se riegan las plantas del jardín?")

    assert results[0].section == "Jardín"
    assert results[0].title == "Manual de la casa"
    assert "martes" in results[0].content


@pytest.mark.db
async def test_saludo_no_trae_contexto(indexed, session: AsyncSession):
    retrieval = RetrievalService(session, FakeEmbedder(), FAKE_SETTINGS)
    assert await retrieval.search("hola buenas") == []


def test_rrf_premia_lo_que_aparece_en_ambas_listas():
    class Item:
        def __init__(self, cid: int) -> None:
            self.chunk = type("C", (), {"id": cid})()

    vector = [Item(1), Item(2), Item(3)]
    words = [Item(3), Item(4)]
    scores = reciprocal_rank_fusion(vector, words)
    assert max(scores, key=scores.get) == 3


# ---------- Prompt y citas ----------


def make_chunk(n: int, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=n, content=text, title="Manual", section=f"S{n}", uri=None, score=1, similarity=0.8
    )


def test_el_contexto_va_numerado_dentro_del_mensaje_del_usuario():
    messages = build_messages([], "¿Cuándo se riega?", [make_chunk(1, "Los martes.")])

    assert len(messages) == 1 and messages[0].role == "user"
    content = messages[0].content
    assert "[1] Manual — S1\nLos martes." in content
    assert content.endswith("Pregunta: ¿Cuándo se riega?")
    assert "cita la fuente" in content


def test_sin_contexto_la_pregunta_va_sola():
    assert build_messages([], "Hola")[0].content == "Hola"


def test_solo_cuenta_las_citas_validas():
    assert cited_numbers("Según [1] y [3], también [9].", available=3) == [1, 3]


# ---------- Chat con RAG ----------


@pytest.fixture
async def owner(session: AsyncSession) -> User:
    user = User(username="dueno", display_name="Dueño", password_hash="!", role="owner")
    session.add_all([user, ModelVersion(ollama_tag="jarvis:base", base_model="Q", kind="base")])
    await session.commit()
    return user


@pytest.mark.db
async def test_chat_envia_fuentes_y_las_guarda(
    indexed, owner: User, session_factory: async_sessionmaker
):
    llm = FakeLLM("Se riegan los martes y viernes [1].")
    embedder = FakeEmbedder()
    service = ChatService(
        session_factory,
        llm,
        "jarvis:base",
        lambda s: RetrievalService(s, embedder, FAKE_SETTINGS),
    )

    events = [e async for e in service.answer(owner.id, "¿Qué días se riegan las plantas?")]
    types = [e["type"] for e in events]

    assert types[:3] == ["start", "searching", "sources"]
    assert events[2]["sources"][0]["section"] == "Jardín"
    assert events[-1]["cited"] == [1]
    # El modelo recibió el contexto numerado.
    assert "[1] Manual de la casa — Jardín" in llm.calls[0][-1].content
    async with session_factory() as s:
        saved = (await s.scalars(select(MessageSource))).all()
    assert saved and saved[0].rank == 1


@pytest.mark.db
async def test_si_falla_la_busqueda_responde_igual(owner: User, session_factory):
    llm = FakeLLM("Hola.")
    service = ChatService(
        session_factory,
        llm,
        "jarvis:base",
        lambda s: RetrievalService(s, FakeEmbedder(fail=True), FAKE_SETTINGS),
    )
    events = [e async for e in service.answer(owner.id, "Hola")]
    assert [e["type"] for e in events][-1] == "end"
    assert "sources" not in [e["type"] for e in events]


# ---------- Endpoints ----------


@pytest.mark.db
async def test_endpoints_de_conocimiento(test_db_url: str):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import Settings, get_settings
    from app.core.dependencies import get_embedder, get_session_factory
    from app.main import create_app

    engine = create_async_engine(test_db_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(User(username="dueno", display_name="Dueño", password_hash="!", role="owner"))
        await s.commit()

    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    app.dependency_overrides[get_settings] = lambda: Settings(
        rag_min_similarity=0.2, rag_min_similarity_with_keywords=0.1
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        async with client:
            created = await client.post(
                "/api/knowledge/text", json={"title": "Manual de la casa", "text": MANUAL}
            )
            assert created.status_code == 201
            assert created.json()["chunks"] == 3

            sources = (await client.get("/api/knowledge/sources")).json()
            assert sources[0]["name"] == "Notas" and sources[0]["chunks"] == 3

            found = (await client.get("/api/knowledge/search", params={"q": "horno cocina"})).json()
            assert found[0]["section"] == "Cocina"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE users, sources RESTART IDENTITY CASCADE"))
        await engine.dispose()


@pytest.mark.parametrize(
    ("text", "small"),
    [
        ("Gracias, Jarvis.", True),
        ("Jarvis, ¿cómo estás?", True),
        ("¿Qué hora es?", True),
        ("¿Quién escribió Cien años de soledad?", False),
        ("¿En qué puerto escucha la base de datos?", False),
    ],
)
def test_charla_corta_no_busca_documentos(text: str, small: bool):
    from app.services.chat_service import is_small_talk

    assert is_small_talk(text) is small


@pytest.mark.parametrize(
    ("text", "search"),
    [
        ("¿Quién escribió Cien años de soledad?", True),
        ("Jarvis, explíqueme cómo se riegan las plantas de la casa", True),
        ("Dime en qué puerto escucha la base de datos", True),
        ("Recuérdame comprar leche mañana a las 8 de la mañana.", False),
        ("Me gusta el café sin azúcar por las mañanas.", False),
        ("¿Qué hora es?", False),  # charla corta
    ],
)
def test_por_voz_solo_las_preguntas_buscan_documentos(text: str, search: bool):
    from app.services.chat_service import voice_needs_documents

    assert voice_needs_documents(text) is search


@pytest.mark.db
async def test_por_voz_la_charla_corta_no_usa_documentos(indexed, owner, session_factory):
    calls = []

    class SpyRetriever:
        async def search(self, query, owner_user_id=None):
            calls.append(query)
            return []

    service = ChatService(
        session_factory, FakeLLM("De nada."), "jarvis:base", lambda s: SpyRetriever()
    )
    [e async for e in service.answer(owner.id, "Gracias, Jarvis.", voice=True)]
    [e async for e in service.answer(owner.id, "Gracias, Jarvis.", voice=False)]
    assert calls == ["Gracias, Jarvis."]  # sólo el modo texto buscó
