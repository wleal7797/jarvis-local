"""Contratos JSON del chat."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000, examples=["Hola JARVIS, ¿cómo estás?"])
    conversation_id: int | None = Field(
        default=None, description="Vacío para empezar una conversación nueva."
    )
    voice: bool = Field(
        default=False, description="Sólo WebSocket: además del texto, enviar la respuesta hablada."
    )


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    channel: str
    created_at: datetime
    updated_at: datetime


class SourceRef(BaseModel):
    n: int
    chunk_id: int
    title: str | None
    section: str | None
    uri: str | None
    similarity: float | None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: datetime
    tokens_out: int | None
    latency_ms: int | None
    sources: list[SourceRef] = []
    rating: int | None = None  # 1 = 👍, -1 = 👎
