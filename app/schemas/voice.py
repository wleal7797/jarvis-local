"""Contratos JSON de la voz."""

from pydantic import BaseModel, Field


class VoiceInfo(BaseModel):
    name: str
    language: str
    speaker: str
    quality: str


class VoiceSettingsOut(BaseModel):
    voice: str
    length_scale: float
    installed: list[VoiceInfo]


class VoiceSettingsIn(BaseModel):
    voice: str | None = Field(default=None, examples=["es_ES-davefx-medium"])
    length_scale: float | None = Field(
        default=None, ge=0.5, le=2.0, description="1.0 normal · >1 más despacio · <1 más rápido"
    )


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class AgentStatusIn(BaseModel):
    state: str = Field(examples=["pensando"])
    text: str = Field(default="", max_length=500)


class AgentStatusOut(BaseModel):
    state: str
    text: str
    at: float


class WarmOut(BaseModel):
    stt: bool
    tts: bool
    llm: bool


class TranscriptionOut(BaseModel):
    text: str
    language: str
    audio_seconds: float
    processing_seconds: float
