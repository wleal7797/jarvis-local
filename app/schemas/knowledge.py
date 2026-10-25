"""Contratos JSON del conocimiento (documentos y búsqueda)."""

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


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


class WebIn(BaseModel):
    url: HttpUrl = Field(examples=["https://es.wikipedia.org/wiki/Bogot%C3%A1"])
    max_pages: int = Field(default=1, ge=1, le=50, description="Páginas del mismo sitio a seguir")


class WikipediaIn(BaseModel):
    titles: list[str] = Field(
        default_factory=list, max_length=500, examples=[["Bogotá", "Café de Colombia"]]
    )
    category: str | None = Field(default=None, max_length=200, examples=["Inteligencia artificial"])
    limit: int = Field(default=50, ge=1, le=500)
    language: str = Field(default="es", pattern=r"^[a-z]{2,3}$")


class JobOut(BaseModel):
    id: int
    type: str
    label: str
    source_name: str
    status: str
    docs_done: int
    docs_total: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
