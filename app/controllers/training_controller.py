"""Controlador de entrenamiento: lo que JARVIS recuerda de usted y las calificaciones 👍 / 👎.

- `/api/memories`: ver, agregar, corregir y borrar recuerdos (panel "Memoria").
- `/api/messages/{id}/feedback`: calificar una respuesta y, con 👎, escribir la correcta.
"""

from fastapi import APIRouter, HTTPException, status

from app.core.dependencies import CurrentUserDep, MemoryServiceDep, TrainingServiceDep
from app.schemas.memory import (
    FeedbackIn,
    FeedbackOut,
    LearnedOut,
    MemoryIn,
    MemoryOut,
    MemoryUpdate,
)
from app.services.embedding_service import EmbeddingError
from app.services.memory_service import MemoryNotFoundError
from app.services.training_service import MessageNotRatableError

router = APIRouter(prefix="/api", tags=["memoria y entrenamiento"])

NOT_FOUND = "Recuerdo no encontrado"
NO_EMBEDDINGS = "No se pudo calcular el significado del texto: ¿está encendido Ollama?"


@router.get("/memories", response_model=list[MemoryOut], summary="Lo que JARVIS recuerda de usted")
async def list_memories(user: CurrentUserDep, memory: MemoryServiceDep):
    return await memory.all_for(user.id)


@router.post(
    "/memories",
    response_model=LearnedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Enseñarle algo (si ya sabía algo casi igual, lo reemplaza)",
)
async def add_memory(body: MemoryIn, user: CurrentUserDep, memory: MemoryServiceDep):
    try:
        return await memory.add(user.id, body.content, body.importance)
    except EmbeddingError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NO_EMBEDDINGS) from None


@router.patch("/memories/{memory_id}", response_model=MemoryOut, summary="Corregir un recuerdo")
async def update_memory(
    memory_id: int, body: MemoryUpdate, user: CurrentUserDep, memory: MemoryServiceDep
):
    try:
        return await memory.update(user.id, memory_id, body.content, body.importance)
    except MemoryNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND) from None
    except EmbeddingError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NO_EMBEDDINGS) from None


@router.delete(
    "/memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Olvidar un recuerdo",
)
async def delete_memory(memory_id: int, user: CurrentUserDep, memory: MemoryServiceDep):
    try:
        await memory.delete(user.id, memory_id)
    except MemoryNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND) from None


@router.put(
    "/messages/{message_id}/feedback",
    response_model=FeedbackOut,
    summary="Calificar una respuesta (👍 / 👎) y, si quiere, escribir la correcta",
)
async def rate_message(
    message_id: int, body: FeedbackIn, user: CurrentUserDep, training: TrainingServiceDep
):
    try:
        rating = await training.rate(user.id, message_id, body.rating, body.correction)
    except MessageNotRatableError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Respuesta no encontrada") from None
    return FeedbackOut(**vars(rating))
