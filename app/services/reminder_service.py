"""Recordatorios que avisan (Etapa 13).

- El modelo de lenguaje NO calcula horas (se equivoca: "en 10 minutos" a las 7:40 le daba
  20:40). Sólo entrega piezas simples: `en_minutos`, `hora` ("21:00", "9 pm") y `fecha`
  ("2026-10-28", "mañana"). Este servicio calcula la fecha exacta.
- Un vigilante en la API revisa cada 10 s los recordatorios vencidos y los entrega por
  `NoticeHub` a quien los creó: el agente de voz los dice en voz alta y la página los muestra.
- Si JARVIS estaba apagado a esa hora, avisa al encenderse ("tenía pendiente…").
"""

import asyncio
import contextlib
import logging
import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Reminder
from app.services.prompt_builder import spanish_date

logger = logging.getLogger(__name__)

MAX_DAYS_AHEAD = 366
LATE_AFTER = timedelta(minutes=2)
CHECK_EVERY_SECONDS = 10

_HOUR = re.compile(
    r"^\s*(\d{1,2})(?:[:.h](\d{2}))?\s*(a\.?\s?m\.?|p\.?\s?m\.?|de la ma[ñn]ana|de la tarde|"
    r"de la noche|del mediod[ií]a)?\s*$",
    re.IGNORECASE,
)


class ReminderError(ValueError):
    """No se pudo entender cuándo avisar."""


def parse_hour(text: str) -> tuple[int, int]:
    """'21:00', '9 pm', '9 de la noche', '7.30' → (hora, minutos) en 24 h."""
    match = _HOUR.match(text.strip())
    if not match:
        raise ReminderError(f"No entendí la hora «{text}». Use por ejemplo 21:00 o 9 pm.")
    hour, minute, period = int(match.group(1)), int(match.group(2) or 0), match.group(3)
    period = _plain(period or "")
    if period.startswith("p") or "tarde" in period or "noche" in period:
        if hour < 12:
            hour += 12
    elif (period.startswith("a") or "manana" in period) and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ReminderError(f"La hora «{text}» no existe.")
    return hour, minute


def parse_date(text: str, today: datetime) -> datetime:
    """'2026-10-28', 'hoy', 'mañana', 'pasado mañana' → fecha."""
    plain = _plain(text)
    relative = {"hoy": 0, "manana": 1, "pasado manana": 2}
    if plain in relative:
        return today + timedelta(days=relative[plain])
    try:
        return datetime.fromisoformat(text.strip()[:10]).replace(tzinfo=today.tzinfo)
    except ValueError:
        raise ReminderError(f"No entendí la fecha «{text}». Use AAAA-MM-DD.") from None


def due_time(
    now: datetime,
    *,
    in_minutes: float | None = None,
    hour: str | None = None,
    date: str | None = None,
) -> datetime:
    """Cuándo avisar, a partir de lo que entendió el modelo."""
    if in_minutes is not None:
        if in_minutes <= 0:
            raise ReminderError("Los minutos deben ser más de cero.")
        due = now + timedelta(minutes=float(in_minutes))
    elif hour:
        h, m = parse_hour(hour)
        day = parse_date(date, now) if date else now
        due = day.replace(hour=h, minute=m, second=0, microsecond=0)
        if not date and due <= now:
            due += timedelta(days=1)  # "a las 7" cuando ya pasaron las 7: mañana
    elif date:
        due = parse_date(date, now).replace(hour=9, minute=0, second=0, microsecond=0)
    else:
        raise ReminderError("Falta cuándo: la hora o en cuántos minutos.")
    if due <= now:
        raise ReminderError("Esa hora ya pasó.")
    if due - now > timedelta(days=MAX_DAYS_AHEAD):
        raise ReminderError("Sólo puedo programar recordatorios hasta dentro de un año.")
    return due


def describe(due: datetime, now: datetime) -> str:
    """'hoy a las 9:00 p. m.', 'mañana a las 7:00 a. m.', 'el viernes 31 de octubre…'"""
    hour = spanish_date(due).split(", ")[-1]
    days = (due.date() - now.date()).days
    if days == 0:
        return f"hoy a las {hour}"
    if days == 1:
        return f"mañana a las {hour}"
    return f"el {spanish_date(due, with_time=False)} a las {hour}"


def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return " ".join(normalized.split())


# ---------- Avisos en vivo, por usuario ----------


class NoticeHub:
    """Entrega avisos (recordatorios vencidos) a las páginas y al agente de cada usuario.
    Si en ese momento no hay nadie conectado, los guarda hasta que alguien se conecte."""

    def __init__(self, backlog: int = 20) -> None:
        self._subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)
        self._pending: dict[int, list[dict]] = defaultdict(list)
        self._backlog = backlog

    def publish(self, user_id: int, notice: dict) -> int:
        queues = self._subscribers.get(user_id) or set()
        if not queues:
            self._pending[user_id] = (self._pending[user_id] + [notice])[-self._backlog :]
            return 0
        for queue in queues:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(notice)
        return len(queues)

    def subscribe(self, user_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        for notice in self._pending.pop(user_id, []):
            queue.put_nowait(notice)
        self._subscribers[user_id].add(queue)
        return queue

    def unsubscribe(self, user_id: int, queue: asyncio.Queue) -> None:
        self._subscribers[user_id].discard(queue)


# ---------- Servicio ----------


class ReminderService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now().astimezone())

    def now(self) -> datetime:
        return self._clock()

    async def create(
        self,
        user_id: int,
        text: str,
        *,
        in_minutes: float | None = None,
        hour: str | None = None,
        date: str | None = None,
    ) -> Reminder:
        text = " ".join(text.split()).strip(" .")
        if not text:
            raise ReminderError("Falta qué recordar.")
        due = due_time(self.now(), in_minutes=in_minutes, hour=hour, date=date)
        async with self._session_factory() as session:
            reminder = Reminder(user_id=user_id, text=text[:300], due_at=due)
            session.add(reminder)
            await session.commit()
            await session.refresh(reminder)
            return reminder

    async def pending(self, user_id: int) -> Sequence[Reminder]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(Reminder)
                .where(Reminder.user_id == user_id, Reminder.fired_at.is_(None))
                .order_by(Reminder.due_at)
            )
            return rows.all()

    async def cancel(self, user_id: int, description: str) -> Reminder | None:
        """Borra el pendiente que más se parece a la descripción ("el de la basura")."""
        wanted = set(_plain(description).split())
        best, best_score = None, 0
        for reminder in await self.pending(user_id):
            score = len(wanted & set(_plain(reminder.text).split()))
            if score > best_score:
                best, best_score = reminder, score
        if best is None:
            return None
        async with self._session_factory() as session:
            found = await session.get(Reminder, best.id)
            if found is not None:
                await session.delete(found)
                await session.commit()
        return best

    async def take_due(self) -> list[Reminder]:
        """Marca como avisados los vencidos y los devuelve (cada uno sale una sola vez)."""
        now = self.now()
        async with self._session_factory() as session:
            rows = await session.scalars(
                update(Reminder)
                .where(Reminder.fired_at.is_(None), Reminder.due_at <= now)
                .values(fired_at=now)
                .returning(Reminder)
            )
            due = list(rows.all())
            for reminder in due:
                reminder.late = now - reminder.due_at > LATE_AFTER
            await session.commit()
            return due

    def notice(self, reminder: Reminder) -> dict:
        when = spanish_date(reminder.due_at.astimezone(self.now().tzinfo)).split(", ")[-1]
        if reminder.late:
            say = f"Señor, tenía pendiente un recordatorio de las {when}: {reminder.text}."
        else:
            say = f"Señor, le recuerdo: {reminder.text}."
        return {
            "type": "recordatorio",
            "id": reminder.id,
            "text": reminder.text,
            "say": say,
            "due_at": reminder.due_at.isoformat(),
            "late": reminder.late,
        }

    async def run_watcher(self, hub: NoticeHub, every_seconds: float = CHECK_EVERY_SECONDS) -> None:
        """Tarea en segundo plano (la arranca `main.py`)."""
        while True:
            try:
                for reminder in await self.take_due():
                    delivered = hub.publish(reminder.user_id, self.notice(reminder))
                    logger.info("recordatorio", extra={"id": reminder.id, "entregado_a": delivered})
            except Exception as exc:  # una falla no debe matar al vigilante
                logger.warning(
                    "no se pudieron revisar los recordatorios", extra={"error": str(exc)}
                )
            await asyncio.sleep(every_seconds)
