"""Controlador de recordatorios (Etapa 13).

- `GET /api/reminders` · `DELETE /api/reminders/{id}`: los pendientes de cada uno.
- `WS /ws/avisos`: entrega en vivo los recordatorios vencidos **sólo a quien los creó**
  (la página los muestra y el agente de voz del dueño los dice en voz alta).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from app.core.dependencies import (
    CurrentUserDep,
    NoticeHubDep,
    ReminderServiceDep,
    SessionFactoryDep,
    require_member,
)
from app.models import Reminder

router = APIRouter(prefix="/api", tags=["recordatorios"], dependencies=[Depends(require_member)])
ws_router = APIRouter(tags=["recordatorios"])


class ReminderOut(BaseModel):
    id: int
    text: str
    due_at: datetime


@router.get("/reminders", response_model=list[ReminderOut], summary="Mis recordatorios pendientes")
async def list_reminders(user: CurrentUserDep, reminders: ReminderServiceDep):
    return [
        ReminderOut(id=r.id, text=r.text, due_at=r.due_at) for r in await reminders.pending(user.id)
    ]


@router.delete(
    "/reminders/{reminder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancelar un recordatorio",
)
async def delete_reminder(reminder_id: int, user: CurrentUserDep, factory: SessionFactoryDep):
    async with factory() as session:
        reminder = await session.get(Reminder, reminder_id)
        if reminder is None or reminder.user_id != user.id or reminder.fired_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Recordatorio no encontrado")
        await session.delete(reminder)
        await session.commit()


@ws_router.websocket("/ws/avisos")
async def notices_socket(websocket: WebSocket, user: CurrentUserDep, hub: NoticeHubDep) -> None:
    await websocket.accept()
    queue = hub.subscribe(user.id)
    try:
        while True:
            await websocket.send_json(await queue.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(user.id, queue)
