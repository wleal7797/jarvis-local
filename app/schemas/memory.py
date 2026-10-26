"""Contratos JSON de la memoria y las calificaciones."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: str
    importance: int
    source_message_id: int | None
    created_at: datetime


class MemoryIn(BaseModel):
    content: str = Field(min_length=3, max_length=300, examples=["Le gusta el café sin azúcar."])
    importance: int = Field(default=3, ge=1, le=5)


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=3, max_length=300)
    importance: int | None = Field(default=None, ge=1, le=5)


class LearnedOut(BaseModel):
    memory_id: int
    content: str
    updated: bool


class FeedbackIn(BaseModel):
    rating: Literal[1, -1] = Field(description="1 = 👍, -1 = 👎")
    correction: str | None = Field(
        default=None, max_length=4000, description="Con 👎: cuál debió ser la respuesta."
    )


class FeedbackOut(BaseModel):
    message_id: int
    rating: int
    correction: str | None
    training_example: bool
