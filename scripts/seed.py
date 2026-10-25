"""Datos iniciales: registra los modelos de chat disponibles en Ollama.

Se puede ejecutar varias veces sin duplicar nada:
    .venv\\Scripts\\python -m scripts.seed
"""

import asyncio

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.models import ModelVersion
from app.repositories import ModelVersionRepository

BASE_MODELS = [
    ModelVersion(
        ollama_tag="qwen3:4b-instruct",
        base_model="Qwen3-4B-Instruct-2507",
        kind="base",
        quantization="Q4_K_M",
        notes="Modelo de chat principal: responde directo, sin razonamiento visible.",
    ),
    ModelVersion(
        ollama_tag="qwen3:4b",
        base_model="Qwen3-4B",
        kind="base",
        quantization="Q4_K_M",
        notes="Variante con razonamiento: más lenta, útil para comparar en la Etapa 3.",
    ),
]


async def seed() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url())
    factory = create_session_factory(engine)
    async with factory() as session:
        repo = ModelVersionRepository(session)
        for model in BASE_MODELS:
            if await repo.get_by_tag(model.ollama_tag) is None:
                await repo.add(model)
                print(f"+ modelo registrado: {model.ollama_tag}")
            else:
                print(f"= ya existía: {model.ollama_tag}")
        if await repo.get_active() is None:
            active = await repo.get_by_tag(settings.ollama_chat_model)
            if active is not None:
                await repo.set_active(active)
                print(f"* modelo activo: {active.ollama_tag}")
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
