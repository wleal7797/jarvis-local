"""Módulo de entrenamiento: datasets, ejemplos, trabajos y versiones de modelo."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, IdMixin, check_in
from app.models.knowledge import JOB_STATUSES

EXAMPLE_ORIGINS = ("public", "feedback", "manual", "synthetic")
RUN_LOCATIONS = ("local", "colab", "kaggle")
MODEL_KINDS = ("base", "lora")


class TrainingDataset(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "training_datasets"

    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    # Si es True, el sistema impide enviarlo a Colab o Kaggle.
    contains_personal_data: Mapped[bool] = mapped_column(server_default=text("false"))

    examples: Mapped[list["TrainingExample"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )


class TrainingExample(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "training_examples"
    __table_args__ = (check_in("origin", EXAMPLE_ORIGINS, "origin"),)

    dataset_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_datasets.id", ondelete="CASCADE")
    )
    origin: Mapped[str]
    feedback_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("feedback.id", ondelete="SET NULL")
    )
    system_prompt: Mapped[str | None]
    user_prompt: Mapped[str]
    assistant_answer: Mapped[str]

    dataset: Mapped[TrainingDataset] = relationship(back_populates="examples", lazy="raise")


class TrainingJob(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "training_jobs"
    __table_args__ = (
        check_in("run_location", RUN_LOCATIONS, "run_location"),
        check_in("status", JOB_STATUSES, "status"),
    )

    dataset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("training_datasets.id"))
    base_model: Mapped[str]
    run_location: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=text("'queued'"))
    hyperparams: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    log_path: Mapped[str | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class ModelVersion(IdMixin, CreatedAtMixin, Base):
    """Un modelo disponible en Ollama: uno base o uno ajustado con LoRA."""

    __tablename__ = "model_versions"
    __table_args__ = (
        check_in("kind", MODEL_KINDS, "kind"),
        # Sólo un modelo activo a la vez.
        Index(
            "uq_model_versions_one_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    ollama_tag: Mapped[str] = mapped_column(unique=True)  # ej. 'qwen3:4b-instruct', 'jarvis:v1'
    base_model: Mapped[str]
    kind: Mapped[str]
    quantization: Mapped[str | None]  # ej. 'Q4_K_M'
    gguf_path: Mapped[str | None]
    training_job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("training_jobs.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("false"))
    notes: Mapped[str | None]
