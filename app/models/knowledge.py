"""Conocimiento: fuentes, documentos, fragmentos vectorizados y tareas de ingesta."""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import EMBEDDING_DIM, Base, CreatedAtMixin, IdMixin, check_in

SOURCE_KINDS = ("file", "web", "wikipedia", "manual")
DOCUMENT_STATUSES = ("pending", "processing", "indexed", "error")
JOB_STATUSES = ("queued", "running", "done", "failed", "cancelled")


class Source(IdMixin, CreatedAtMixin, Base):
    """De dónde viene el conocimiento (un archivo, un sitio web, Wikipedia…)."""

    __tablename__ = "sources"
    __table_args__ = (
        check_in("kind", SOURCE_KINDS, "kind"),
        # Un documento personal siempre tiene dueño.
        CheckConstraint("NOT is_personal OR owner_user_id IS NOT NULL", name="personal_has_owner"),
    )

    kind: Mapped[str]
    name: Mapped[str]
    base_uri: Mapped[str | None]
    license: Mapped[str | None]
    is_personal: Mapped[bool] = mapped_column(server_default=text("false"))
    owner_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE")
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="source", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )


class Document(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        check_in("status", DOCUMENT_STATUSES, "status"),
        Index("ix_documents_source_status", "source_id", "status"),
    )

    source_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sources.id", ondelete="CASCADE"))
    title: Mapped[str | None]
    uri: Mapped[str | None]
    mime_type: Mapped[str | None]
    language: Mapped[str | None]
    content_hash: Mapped[str] = mapped_column(unique=True)  # SHA-256: evita duplicados
    status: Mapped[str] = mapped_column(server_default=text("'pending'"))
    error_message: Mapped[str | None]
    indexed_at: Mapped[datetime | None]

    source: Mapped[Source] = relationship(back_populates="documents", lazy="raise")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Chunk.chunk_index",
        lazy="raise",
    )


class Chunk(IdMixin, Base):
    """Un fragmento de ~500 tokens de un documento, con su vector."""

    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uq_chunks_position"),)

    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int]
    content: Mapped[str]
    token_count: Mapped[int | None]
    embedding: Mapped[list[float] | None] = mapped_column(HALFVEC(EMBEDDING_DIM))
    # Columna calculada por PostgreSQL para búsqueda por palabras clave.
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('spanish', content)", persisted=True)
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", server_default=text("'{}'::jsonb")
    )

    document: Mapped[Document] = relationship(back_populates="chunks", lazy="raise")


# Búsqueda por significado (vectorial, distancia coseno).
Index(
    "ix_chunks_embedding_hnsw",
    Chunk.embedding,
    postgresql_using="hnsw",
    postgresql_with={"m": 16, "ef_construction": 64},
    postgresql_ops={"embedding": "halfvec_cosine_ops"},
)
# Búsqueda por palabras clave.
Index("ix_chunks_tsv_gin", Chunk.tsv, postgresql_using="gin")


class IngestionJob(IdMixin, CreatedAtMixin, Base):
    """Tarea en cola para el worker de ingesta (Etapa 6)."""

    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        check_in("status", JOB_STATUSES, "status"),
        Index("ix_ingestion_jobs_status_created", "status", "created_at"),
    )

    source_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sources.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(server_default=text("'queued'"))
    params: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    docs_total: Mapped[int] = mapped_column(server_default=text("0"))
    docs_done: Mapped[int] = mapped_column(server_default=text("0"))
    error_message: Mapped[str | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    source: Mapped[Source] = relationship(lazy="raise")
