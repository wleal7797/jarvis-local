"""Conexión a PostgreSQL con SQLAlchemy asíncrono (driver asyncpg)."""

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(url: str) -> AsyncEngine:
    # Pocas conexiones: es un PC de casa con 8 GB de RAM, no un servidor con miles de usuarios.
    return create_async_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def ping(engine: AsyncEngine) -> str:
    """Comprueba la conexión y devuelve la versión de pgvector instalada."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        version = result.scalar_one_or_none()
    if version is None:
        raise RuntimeError("La extensión pgvector no está instalada")
    return version


async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """Una sesión por petición: confirma al terminar bien, deshace si hay error."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
