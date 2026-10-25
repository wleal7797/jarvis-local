"""Contratos JSON del conocimiento (documentos y búsqueda)."""

from pydantic import BaseModel, Field


class TextIn(BaseModel):
    title: str = Field(min_length=1, max_length=200, examples=["Horario de la casa"])
    text: str = Field(min_length=1, max_length=500_000)
    source_name: str = Field(default="Notas", max_length=100)
    personal: bool = Field(
        default=False, description="Si es True, sólo lo ve el usuario que lo agregó."
    )


class IndexOut(BaseModel):
    document_id: int
    title: str | None
    chunks: int
    created: bool


class SourceOut(BaseModel):
    id: int
    kind: str
    name: str
    is_personal: bool
    documents: int
    chunks: int


class SearchResultOut(BaseModel):
    chunk_id: int
    title: str | None
    section: str | None
    uri: str | None
    similarity: float | None
    score: float
    content: str
