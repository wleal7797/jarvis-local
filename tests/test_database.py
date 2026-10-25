"""Pruebas de la base de datos: esquema, búsqueda vectorial y reglas de integridad."""

import hashlib

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EMBEDDING_DIM, Chunk, Document, ModelVersion, Source, User
from app.repositories import ChunkRepository, ModelVersionRepository

pytestmark = [pytest.mark.anyio, pytest.mark.db]

EXPECTED_TABLES = {
    "users",
    "conversations",
    "messages",
    "message_sources",
    "feedback",
    "memories",
    "sources",
    "documents",
    "chunks",
    "ingestion_jobs",
    "training_datasets",
    "training_examples",
    "training_jobs",
    "model_versions",
}


def axis_vector(*weights: tuple[int, float]) -> list[float]:
    """Vector de 1024 dimensiones con valores sólo en las posiciones indicadas."""
    vector = [0.0] * EMBEDDING_DIM
    for position, value in weights:
        vector[position] = value
    return vector


async def make_document(
    session: AsyncSession, chunks: list[tuple[str, list[float]]], **source_fields
) -> Document:
    source = Source(kind="manual", name="Pruebas", **source_fields)
    first_text = chunks[0][0]
    document = Document(
        source=source,
        title="Documento de prueba",
        content_hash=hashlib.sha256(f"{source_fields}{first_text}".encode()).hexdigest(),
        status="indexed",
    )
    document.chunks = [
        Chunk(chunk_index=i, content=content, embedding=embedding)
        for i, (content, embedding) in enumerate(chunks)
    ]
    session.add(document)
    await session.flush()
    return document


async def make_user(session: AsyncSession, username: str = "dueno") -> User:
    user = User(username=username, display_name="Dueño", password_hash="x", role="owner")
    session.add(user)
    await session.flush()
    return user


async def test_migracion_crea_todas_las_tablas(session: AsyncSession):
    result = await session.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    )
    tables = set(result.scalars())
    assert tables >= EXPECTED_TABLES


async def test_busqueda_vectorial_devuelve_el_mas_parecido(session: AsyncSession):
    await make_document(
        session,
        [
            ("Historia de Bogotá", axis_vector((0, 1.0))),
            ("Recetas de cocina", axis_vector((1, 1.0))),
            ("Partidos de fútbol", axis_vector((2, 1.0))),
        ],
    )
    # Consulta "casi igual" al segundo fragmento.
    query = axis_vector((1, 0.9), (0, 0.1))

    results = await ChunkRepository(session).nearest(query, k=2)

    assert [r.chunk.content for r in results] == ["Recetas de cocina", "Historia de Bogotá"]
    assert results[0].score > 0.99
    assert results[0].score > results[1].score


async def test_documentos_personales_solo_los_ve_su_dueno(session: AsyncSession):
    owner = await make_user(session)
    await make_document(
        session,
        [("Mi cumpleaños es el 7 de marzo", axis_vector((5, 1.0)))],
        is_personal=True,
        owner_user_id=owner.id,
    )
    repo = ChunkRepository(session)
    query = axis_vector((5, 1.0))

    assert await repo.nearest(query, k=5) == []
    visibles = await repo.nearest(query, k=5, owner_user_id=owner.id)
    assert [r.chunk.content for r in visibles] == ["Mi cumpleaños es el 7 de marzo"]


async def test_busqueda_por_palabras_en_espanol(session: AsyncSession):
    await make_document(
        session,
        [
            ("Bogotá fue fundada en 1538 por Gonzalo Jiménez de Quesada.", axis_vector((0, 1.0))),
            ("El café colombiano se exporta a todo el mundo.", axis_vector((1, 1.0))),
        ],
    )
    repo = ChunkRepository(session)

    # El diccionario 'spanish' reduce las conjugaciones a su raíz: fundaron / fundada → "fund".
    results = await repo.full_text("fundaron Bogotá", k=5)
    assert len(results) == 1
    assert "1538" in results[0].chunk.content

    # Pero "fundación" es otra raíz ("fundacion"): para eso existe la búsqueda vectorial.
    assert await repo.full_text("fundación de Bogotá", k=5) == []


async def test_documento_duplicado_es_rechazado(session: AsyncSession):
    source = Source(kind="manual", name="Pruebas")
    session.add_all(
        [
            Document(source=source, content_hash="mismo-hash"),
            Document(source=source, content_hash="mismo-hash"),
        ]
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_documento_personal_sin_dueno_es_rechazado(session: AsyncSession):
    session.add(Source(kind="file", name="Diario", is_personal=True))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_rol_invalido_es_rechazado(session: AsyncSession):
    session.add(User(username="hacker", display_name="X", password_hash="x", role="admin"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_solo_un_modelo_activo(session: AsyncSession):
    repo = ModelVersionRepository(session)
    first = await repo.add(ModelVersion(ollama_tag="a:1", base_model="A", kind="base"))
    second = await repo.add(ModelVersion(ollama_tag="b:1", base_model="B", kind="base"))

    await repo.set_active(first)
    await repo.set_active(second)

    active = await repo.get_active()
    assert active is not None and active.ollama_tag == "b:1"
    await session.refresh(first)
    assert first.is_active is False

    # Activar dos a mano viola el índice único parcial.
    first.is_active = True
    with pytest.raises(IntegrityError):
        await session.flush()
