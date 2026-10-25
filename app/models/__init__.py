"""Modelo (la "M" de MVC): entidades SQLAlchemy.

Siguen docs/arquitectura/05-modelo-relacional.md. Importar este paquete registra
todas las tablas en `Base.metadata` (lo usa Alembic para generar migraciones).
"""

from app.models.base import EMBEDDING_DIM, Base
from app.models.conversation import Conversation, Feedback, Message, MessageSource
from app.models.knowledge import Chunk, Document, IngestionJob, Source
from app.models.memory import Memory
from app.models.training import ModelVersion, TrainingDataset, TrainingExample, TrainingJob
from app.models.user import User

__all__ = [
    "EMBEDDING_DIM",
    "Base",
    "Chunk",
    "Conversation",
    "Document",
    "Feedback",
    "IngestionJob",
    "Memory",
    "Message",
    "MessageSource",
    "ModelVersion",
    "Source",
    "TrainingDataset",
    "TrainingExample",
    "TrainingJob",
    "User",
]
