"""Contratos JSON de la voz."""

from pydantic import BaseModel, Field


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class TranscriptionOut(BaseModel):
    text: str
    language: str
    audio_seconds: float
    processing_seconds: float
