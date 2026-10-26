"""Estado de la conversación por voz: ¿hace falta decir "Jarvis" o ya están hablando?

    DORMIDO ──"Jarvis, …"──► ATENDIENDO ──respuesta──► HABLANDO ──termina──► ESCUCHANDO
       ▲                                                 │ "Jarvis, …"          │
       │                                                 └──► (se calla) ◄──────┤
       └───────────── pasan 8 s sin que nadie hable ◄────────────────────────────┘

- DORMIDO: sólo reacciona si la frase empieza con su nombre.
- ESCUCHANDO (modo conversación): durante unos segundos tras responder, cualquier frase
  es para él, sin repetir el nombre. Así la conversación fluye.
- HABLANDO: su propia voz sale por los parlantes y el micrófono la oye. Sólo se deja
  interrumpir si alguien dice "Jarvis" y lo dicho no es eco de lo que él mismo está diciendo.
- La misma conversación (historial) sigue mientras no pasen 5 minutos sin hablar.
"""

import re
import time
import unicodedata
from dataclasses import dataclass, field
from enum import Enum


class Mode(Enum):
    DORMIDO = "dormido"
    ATENDIENDO = "atendiendo"
    HABLANDO = "hablando"
    ESCUCHANDO = "escuchando"


@dataclass
class ConversationSettings:
    follow_up_seconds: float = 8.0
    session_minutes: float = 5.0
    echo_overlap: float = 0.6  # si el 60 % de las palabras coincide con lo que dice, es eco


def _words(text: str) -> set[str]:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return {w for w in re.findall(r"[a-z0-9]+", plain) if len(w) > 2}


@dataclass
class Conversation:
    settings: ConversationSettings = field(default_factory=ConversationSettings)
    clock: callable = time.monotonic
    mode: Mode = Mode.DORMIDO
    conversation_id: int | None = None
    _listening_until: float = 0.0
    _last_activity: float = 0.0
    _speaking: list[str] = field(default_factory=list)

    # ---------- Decisiones ----------

    def needs_name(self) -> bool:
        """¿Hay que decir "Jarvis" para que atienda?"""
        self._expire()
        return self.mode in (Mode.DORMIDO, Mode.HABLANDO)

    def is_echo(self, heard: str) -> bool:
        """¿Lo que oyó el micrófono es su propia voz saliendo por los parlantes?"""
        heard_words = _words(heard)
        if not heard_words:
            return False
        for sentence in self._speaking:
            spoken = _words(sentence)
            if (
                spoken
                and len(heard_words & spoken) / len(heard_words) >= self.settings.echo_overlap
            ):
                return True
        return False

    # ---------- Eventos ----------

    def attending(self) -> None:
        self.mode = Mode.ATENDIENDO
        self._touch()

    def speaking(self, sentence: str) -> None:
        self.mode = Mode.HABLANDO
        self._speaking = (self._speaking + [sentence])[-6:]
        self._touch()

    def finished_speaking(self) -> None:
        self.mode = Mode.ESCUCHANDO
        self._speaking = []
        self._listening_until = self.clock() + self.settings.follow_up_seconds
        self._touch()

    def interrupted(self) -> None:
        self._speaking = []
        self.attending()

    def started_conversation(self, conversation_id: int) -> None:
        self.conversation_id = conversation_id

    # ---------- Tiempo ----------

    def _touch(self) -> None:
        self._last_activity = self.clock()

    def _expire(self) -> None:
        now = self.clock()
        if self.mode == Mode.ESCUCHANDO and now > self._listening_until:
            self.mode = Mode.DORMIDO
        if now - self._last_activity > self.settings.session_minutes * 60:
            self.conversation_id = None  # tras 5 min de silencio, conversación nueva
