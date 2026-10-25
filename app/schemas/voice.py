"""Contratos JSON de la voz."""

from pydantic import BaseModel


class TranscriptionOut(BaseModel):
    text: str
    language: str
    audio_seconds: float
    processing_seconds: float
