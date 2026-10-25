"""Repositorios (parte del Modelo): el único lugar que habla con la base de datos."""

from app.repositories.base_repository import BaseRepository
from app.repositories.chunk_repository import ChunkRepository, ScoredChunk
from app.repositories.model_version_repository import ModelVersionRepository

__all__ = ["BaseRepository", "ChunkRepository", "ModelVersionRepository", "ScoredChunk"]
