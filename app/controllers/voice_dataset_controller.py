"""Grabar mi voz: el dueño lee frases y se guardan listas para entrenar una voz de Piper.

Sólo el dueño: son grabaciones de su voz. Todo queda en `data/voz-propia/` de este PC.
"""

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel

from app.core.dependencies import OwnerDep, SettingsDep
from app.services.voice_dataset import DatasetError, VoiceDataset

router = APIRouter(prefix="/api/voice/dataset", tags=["voz propia"])

MAX_CLIP_BYTES = 8 * 1024 * 1024


class DatasetOverview(BaseModel):
    total: int
    recorded: int
    minutes: float
    next: int | None
    folder: str


class PhraseOut(BaseModel):
    index: int
    text: str
    recorded: bool


class ClipOut(BaseModel):
    index: int
    seconds: float
    peak: float
    warnings: list[str]


def _dataset(settings) -> VoiceDataset:
    return VoiceDataset(Path(settings.voice_dataset_dir))


def _bad(exc: DatasetError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get("", response_model=DatasetOverview, summary="Cuánto se ha grabado")
async def overview(owner: OwnerDep, settings: SettingsDep):
    return _dataset(settings).overview()


@router.get("/phrases/{index}", response_model=PhraseOut, summary="Una frase para leer")
async def phrase(index: int, owner: OwnerDep, settings: SettingsDep):
    dataset = _dataset(settings)
    try:
        return PhraseOut(
            index=index, text=dataset.phrase(index), recorded=index in dataset.recorded()
        )
    except DatasetError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None


@router.post(
    "/phrases/{index}",
    response_model=ClipOut,
    status_code=status.HTTP_201_CREATED,
    summary="Guardar la grabación de una frase (reemplaza la anterior)",
)
async def record(
    index: int,
    owner: OwnerDep,
    settings: SettingsDep,
    audio: Annotated[UploadFile, File(description="La grabación del navegador")],
):
    data = await audio.read(MAX_CLIP_BYTES + 1)
    if len(data) > MAX_CLIP_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "La grabación es muy larga")
    try:
        report = await asyncio.to_thread(_dataset(settings).save, index, data)
    except DatasetError as exc:
        raise _bad(exc) from None
    return ClipOut(**report.__dict__)


@router.get("/phrases/{index}/audio", summary="Escuchar lo que se grabó")
async def clip_audio(index: int, owner: OwnerDep, settings: SettingsDep) -> Response:
    try:
        wav = _dataset(settings).audio(index)
    except DatasetError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.delete(
    "/phrases/{index}", status_code=status.HTTP_204_NO_CONTENT, summary="Borrar una grabación"
)
async def remove(index: int, owner: OwnerDep, settings: SettingsDep) -> None:
    _dataset(settings).remove(index)


@router.get("/export.zip", summary="Descargar todo lo grabado para entrenar")
async def export(owner: OwnerDep, settings: SettingsDep) -> Response:
    try:
        data = await asyncio.to_thread(_dataset(settings).export_zip)
    except DatasetError as exc:
        raise _bad(exc) from None
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="voz-propia.zip"'},
    )
