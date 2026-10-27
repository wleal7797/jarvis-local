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
    # 4 de los 8 hilos: deja el resto del PC usable mientras calcula vectores.
    ollama_embed_threads: int = 4
    # Libera la RAM de bge-m3 (1,2 GB) poco después de usarlo.
    ollama_embed_keep_alive: str = "2m"

    # RAG: búsqueda en documentos antes de responder (Etapa 5).
    rag_enabled: bool = True
    # 3 y no más: la GTX 1650 Ti lee el contexto a ~250 tokens/s (ver bitácora de la Etapa 5).
    rag_top_k: int = 3
    rag_min_similarity: float = 0.5
    rag_min_similarity_with_keywords: float = 0.42
    # Conversación por voz: menos contexto para empezar a hablar antes (Etapa 9).
    rag_voice_context_tokens: int = 1100
    # Respuestas habladas: tope de tokens (una o dos frases; evita monólogos lentos).
    voice_max_tokens: int = 200

    # Memoria (Etapa 10): recordar lo que el usuario cuenta.
    memory_enabled: bool = True
    memory_token_budget: int = 500

    # Voz a texto (Etapa 7)
    stt_model: str = "small"
    # "auto": GPU si se puede (0,5 s por frase), si no CPU (~3 s). También "cuda" o "cpu".
    stt_device: str = "auto"
    stt_language: str = "es"
    stt_threads: int = 4
    stt_initial_prompt: str = (
        "Conversación en español con Jarvis (se pronuncia Yarbis), el asistente de la casa."
    )
    stt_idle_unload_seconds: int = 300

    # Texto a voz (Etapa 8). Voz elegida escuchando muestras.
    tts_voices_dir: str = "data/tts/piper"
    tts_voice: str = "es_ES-davefx-medium"
    tts_length_scale: float = 1.0
    tts_idle_unload_seconds: int = 600

    # Ingesta (Etapa 6). Apágalo para trabajar 100 % sin conexión.
    ingestion_allow_internet: bool = True
    uploads_dir: str = "data/uploads"

    # El dueño (lo crea scripts/seed.py). Con el inicio de sesión apagado, todos son él.
    default_username: str = "dueno"

    # Inicio de sesión (Etapa 11). Apagarlo sólo en pruebas o si nadie más usa la red.
    auth_enabled: bool = True
    auth_session_days: int = 30
    # Se crean solos en data/ la primera vez (data/ nunca va a Git).
    secret_key_file: str = "data/secret.key"
    agent_token_file: str = "data/agent.token"

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
