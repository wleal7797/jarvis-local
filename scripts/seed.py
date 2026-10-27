"""Datos iniciales: modelos de Ollama y usuario por defecto.

Se puede ejecutar varias veces sin duplicar nada:
    .venv\\Scripts\\python -m scripts.seed
"""

import asyncio

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.models import ModelVersion, User
from app.repositories import ModelVersionRepository, UserRepository

MODELS = [
    ModelVersion(
        ollama_tag="jarvis:base",
        base_model="Qwen3-4B-Instruct-2507",
        kind="base",
        quantization="Q4_K_M",
        notes="qwen3:4b-instruct + personalidad de JARVIS (ollama/Modelfile).",
    ),
    ModelVersion(
        ollama_tag="qwen3:4b-instruct",
        base_model="Qwen3-4B-Instruct-2507",
        kind="base",
        quantization="Q4_K_M",
        notes="Modelo base sin personalidad: responde directo, sin razonamiento visible.",
    ),
    ModelVersion(
        ollama_tag="qwen3:4b",
        base_model="Qwen3-4B",
        kind="base",
        quantization="Q4_K_M",
        notes="Variante con razonamiento: más lenta. Sólo para comparar.",
    ),
]

# Hasta la Etapa 10 no hay inicio de sesión: "!" no es un hash Argon2 válido,
# así que nadie puede entrar con contraseña a esta cuenta.
UNUSABLE_PASSWORD = "!"


async def seed() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url())
    factory = create_session_factory(engine)
    async with factory() as session:
        models = ModelVersionRepository(session)
        for model in MODELS:
            if await models.get_by_tag(model.ollama_tag) is None:
                await models.add(model)
                print(f"+ modelo registrado: {model.ollama_tag}")
            else:
                print(f"= ya existía: {model.ollama_tag}")

        configured = await models.get_by_tag(settings.ollama_chat_model)
        active = await models.get_active()
        # Sólo si no hay ninguno activo: no deshace un `jarvis:v1` activado (Etapa 12).
        if configured is not None and active is None:
            await models.set_active(configured)
            print(f"* modelo activo: {configured.ollama_tag}")

        users = UserRepository(session)
        if await users.get_by_username(settings.default_username) is None:
            await users.add(
                User(
                    username=settings.default_username,
                    display_name="Dueño",
                    password_hash=UNUSABLE_PASSWORD,
                    role="owner",
                )
            )
            print(f"+ usuario por defecto: {settings.default_username}")
        else:
            print(f"= ya existía el usuario: {settings.default_username}")

        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
