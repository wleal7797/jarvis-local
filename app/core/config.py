"""Configuración central de la aplicación.

Los valores se leen de variables de entorno o del archivo `.env`.
Ver `.env.example` para la lista completa.
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "JARVIS"
    app_version: str = "0.1.0"
    environment: Literal["development", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    api_host: str = "127.0.0.1"
    api_port: int = 8000

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_chat_model: str = "jarvis:base"
    ollama_embed_model: str = "bge-m3"
    ollama_timeout_seconds: float = 120.0
    # Los embeddings corren en la CPU para no quitarle VRAM al modelo de chat.
    ollama_embed_on_gpu: bool = False

    # RAG: búsqueda en documentos antes de responder (Etapa 5).
    rag_enabled: bool = True
    # 3 y no más: la GTX 1650 Ti lee el contexto a ~250 tokens/s (ver bitácora de la Etapa 5).
    rag_top_k: int = 3
    rag_min_similarity: float = 0.5
    rag_min_similarity_with_keywords: float = 0.42

    # Usuario con el que se conversa hasta que exista el inicio de sesión (Etapa 10).
    default_username: str = "dueno"

    postgres_user: str = "jarvis"
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "jarvis"
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5434

    def database_url(self, database: str | None = None) -> str:
        """URL de conexión para SQLAlchemy (driver asyncpg)."""
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=database or self.postgres_db,
        ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    """Devuelve la configuración (se lee una sola vez)."""
    return Settings()
