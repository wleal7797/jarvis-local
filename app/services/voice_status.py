"""Qué está haciendo el agente de voz, para mostrarlo en la pantalla.

El agente (`python -m agents.voice`) avisa cada cambio: le escucho → pensando →
(buscando en documentos) → hablando →
le sigo escuchando → en espera. Los navegadores abiertos lo reciben al instante por
WebSocket (`/ws/voice-status`) y lo muestran arriba del chat.

Vive en memoria: si la API se reinicia, vuelve a "apagado" hasta el próximo aviso.
"""

import asyncio
import contextlib
import time
from dataclasses import asdict, dataclass, field
from typing import Literal

AgentState = Literal[
    "apagado", "en_espera", "escuchando", "pensando", "buscando", "hablando", "atento"
]
STATES: tuple[str, ...] = AgentState.__args__  # type: ignore[attr-defined]


@dataclass(frozen=True)
class AgentStatus:
    state: str = "apagado"
    text: str = ""
    at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class VoiceStatusHub:
    def __init__(self, queue_size: int = 20) -> None:
        self.current = AgentStatus()
        self._subscribers: set[asyncio.Queue[AgentStatus]] = set()
        self._queue_size = queue_size

    def publish(self, state: str, text: str = "") -> AgentStatus:
        if state not in STATES:
            raise ValueError(f"Estado desconocido: {state}")
        self.current = AgentStatus(state=state, text=text)
        for queue in list(self._subscribers):
            # Un navegador lento no frena a los demás: si su cola se llena, pierde el aviso.
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(self.current)
        return self.current

    def subscribe(self) -> asyncio.Queue[AgentStatus]:
        queue: asyncio.Queue[AgentStatus] = asyncio.Queue(maxsize=self._queue_size)
        queue.put_nowait(self.current)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[AgentStatus]) -> None:
        self._subscribers.discard(queue)
