"""Repositorios (parte del Modelo): el único lugar que habla con la base de datos."""

from app.repositories.base_repository import BaseRepository
from app.repositories.chunk_repository import ChunkRepository, ScoredChunk
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.model_version_repository import ModelVersionRepository
from app.repositories.user_repository import UserRepository

__all__ = [
    "BaseRepository",
    "ChunkRepository",
    "ConversationRepository",
    "ModelVersionRepository",
    "ScoredChunk",
    "UserRepository",
]
