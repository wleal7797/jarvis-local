"""Fixtures compartidas.

Las pruebas de base de datos usan la base `jarvis_test` (creada por
docker/postgres/init), nunca la base real. Si PostgreSQL no está corriendo,
esas pruebas se saltan con un aviso en lugar de fallar.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models import ModelVersion, User

TEST_DATABASE = "jarvis_test"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


async def _can_connect(url: str) -> bool:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect():
            return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """Base de pruebas recién migrada: borra todo y aplica las migraciones desde cero."""
    url = get_settings().database_url(TEST_DATABASE)
    if not asyncio.run(_can_connect(url)):
        pytest.skip("PostgreSQL de pruebas no disponible: ejecuta `docker compose up -d`")
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    config.attributes["skip_logging"] = True
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return url


@pytest.fixture
async def db_connection(test_db_url: str) -> AsyncIterator[AsyncConnection]:
    """Conexión dentro de una transacción que se deshace al final: cada prueba empieza limpia."""
    engine = create_async_engine(test_db_url, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
    await engine.dispose()


@pytest.fixture
def session_factory(db_connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """Fábrica de sesiones sobre la misma conexión: sus `commit()` se convierten en
    puntos de guardado, así que también se deshacen al terminar la prueba."""
    return async_sessionmaker(
        bind=db_connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as db_session:
        yield db_session


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
                ModelVersion(ollama_tag="jarvis:base", base_model="Qwen3", kind="base"),
            ]
        )
        await session.commit()
    yield factory
    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE users, model_versions, training_datasets RESTART IDENTITY CASCADE")
        )
    await engine.dispose()
