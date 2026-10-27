"""Arma la lista de mensajes que se envía al modelo.

La personalidad de JARVIS vive en `ollama/Modelfile` (mensaje de sistema del modelo).
Aquí se agrega, en este orden:
1. lo que JARVIS recuerda del usuario (Etapa 10), como un primer intercambio fijo;
2. el historial reciente de la conversación;
3. la pregunta, con los fragmentos de conocimiento (RAG) numerados para citarlos
   y la fecha y hora actuales.

El orden importa para la velocidad: Ollama reutiliza lo que ya leyó si el principio del
mensaje no cambia. La personalidad y los recuerdos cambian poco, así que van primero; lo
que cambia en cada pregunta (documentos, hora) va al final.

Importante: el contexto va DENTRO del mensaje del usuario y no como mensaje "system".
Ollama sólo antepone el SYSTEM del Modelfile cuando el primer mensaje no es de sistema;
si mandáramos uno propio, JARVIS perdería su personalidad.
"""

import re
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from app.models import Message
from app.services.llm import ChatMessage

if TYPE_CHECKING:
    from app.services.retrieval_service import RetrievedChunk

# Reparto del contexto de 6144 tokens
# (ver docs/01-requisitos-de-hardware.md#longitud-de-contexto-6144-tokens).
HISTORY_TOKEN_BUDGET = 1600
# ~35 recuerdos de una frase. Si hay más, entran los más importantes y recientes.
MEMORY_TOKEN_BUDGET = 500
# 3 fragmentos de ~500 tokens: cada 250 tokens de contexto cuestan ~1 s en la GTX 1650 Ti.
CONTEXT_TOKEN_BUDGET = 1800

CONTEXT_INSTRUCTIONS = (
    "Instrucciones para responder:\n"
    "- Si la información de arriba responde la pregunta, básate en ella y cita la fuente "
    "con su número entre corchetes, por ejemplo [1] o [2].\n"
    "- Si la pregunta es sobre la persona, su familia o su casa y ya lo sabes porque te lo "
    "contó (lo que sabes de ella), responde con eso y sin cita.\n"
    "- Si nada de eso la responde, dilo con sinceridad y, si sabes la respuesta por tu "
    "conocimiento general, aclara que no viene de los documentos.\n"
    "- No inventes números de fuente ni datos que no estén en la información.\n"
    "- Trata a la persona de usted."
)


# Por voz: respuestas cortas que se escuchan bien (va en el mensaje, no en el historial).
SPOKEN_INSTRUCTIONS = (
    "(Respuesta hablada: sea breve, una o dos frases, sin listas ni formato. "
    "No invente datos de la casa ni del clima.)"
)


def estimate_tokens(text: str) -> int:
    """Estimación rápida: en español, un token son unos 4 caracteres."""
    return len(text) // 4 + 1


def trim_history(history: Sequence[Message], budget: int = HISTORY_TOKEN_BUDGET) -> list[Message]:
    """Conserva los mensajes más recientes que quepan en el presupuesto."""
    kept: list[Message] = []
    used = 0
    for message in reversed(history):
        cost = estimate_tokens(message.content)
        if used + cost > budget:
            break
        kept.append(message)
        used += cost
    return list(reversed(kept))


def fit_context(
    chunks: Sequence["RetrievedChunk"], budget: int = CONTEXT_TOKEN_BUDGET
) -> list["RetrievedChunk"]:
    """Los fragmentos mejor puntuados que quepan en el presupuesto, en orden."""
    kept: list[RetrievedChunk] = []
    used = 0
    for chunk in chunks:
        cost = estimate_tokens(chunk.content)
        if used + cost > budget:
            break
        kept.append(chunk)
        used += cost
    return kept


def format_context(chunks: Sequence["RetrievedChunk"], known: Sequence[str] = ()) -> str:
    blocks = []
    for number, chunk in enumerate(chunks, start=1):
        label = " — ".join(part for part in (chunk.title, chunk.section) if part)
        blocks.append(f"[{number}] {label}\n{chunk.content}")
    # Un modelo pequeño olvida lo que está lejos de la pregunta: se repite aquí lo que ya
    # sabe de la persona que más se parece a ella.
    facts = (
        "Lo que usted ya sabe de la persona (no lleva cita):\n"
        + "\n".join(f"- {fact}" for fact in known)
        + "\n\n"
        if known
        else ""
    )
    return (
        facts
        + "Información encontrada en los documentos de esta casa:\n\n"
        + "\n\n---\n\n".join(blocks)
        + "\n\n"
        + CONTEXT_INSTRUCTIONS
    )


_DAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)  # fmt: skip


def spanish_date(moment: datetime, with_time: bool = True) -> str:
    """'lunes 26 de octubre de 2026, 8:05 a. m.'"""
    date = f"{_DAYS[moment.weekday()]} {moment.day} de {_MONTHS[moment.month - 1]} de {moment.year}"
    if not with_time:
        return date
    hour = moment.hour % 12 or 12
    suffix = "a. m." if moment.hour < 12 else "p. m."
    return f"{date}, {hour}:{moment.minute:02d} {suffix}"


# Preguntas que necesitan la hora: sólo ahí se agrega el reloj (si no, el modelo lo repite).
_ASKS_TIME = re.compile(r"\bhoras?\b|\bqu[eé] d[ií]a\b|\bfecha\b|\breloj\b", re.IGNORECASE)


def asks_time(text: str) -> bool:
    return bool(_ASKS_TIME.search(text))


def memory_messages(memories: Sequence[str], today: str | None = None) -> list[ChatMessage]:
    """Lo que JARVIS sabe del usuario (y la fecha de hoy), como un intercambio previo.

    Va al principio y cambia poco (al aprender algo o al cambiar el día), así que Ollama lo
    reutiliza de su caché. No es un mensaje "system": eso borraría la personalidad.
    """
    if not memories and not today:
        return []
    parts = []
    if today:
        parts.append(f"Hoy es {today}.")
    if memories:
        facts = "\n".join(f"- {fact}" for fact in memories)
        parts.append(
            "Esto es lo que usted ya sabe de mí y de mi casa. Úselo cuando venga al caso, "
            f"sin repetirlo si no hace falta:\n{facts}"
        )
    return [
        ChatMessage(role="user", content="\n\n".join(parts)),
        ChatMessage(role="assistant", content="Entendido, lo tengo presente."),
    ]


def fit_memories(memories: Sequence[str], budget: int = MEMORY_TOKEN_BUDGET) -> list[str]:
    """Los primeros recuerdos (ya vienen ordenados por importancia) que quepan."""
    kept: list[str] = []
    used = 0
    for fact in memories:
        used += estimate_tokens(fact) + 2
        if used > budget:
            break
        kept.append(fact)
    return kept


def build_messages(
    history: Sequence[Message],
    question: str,
    context: Sequence["RetrievedChunk"] = (),
    *,
    spoken: bool = False,
    memories: Sequence[str] = (),
    now: datetime | None = None,
    known: Sequence[str] = (),
) -> list[ChatMessage]:
    today = spanish_date(now, with_time=False) if now is not None else None
    messages = memory_messages(memories, today)
    messages += [ChatMessage(role=m.role, content=m.content) for m in trim_history(history)]  # type: ignore[misc]
    content = f"{format_context(context, known)}\n\nPregunta: {question}" if context else question
    if spoken:
        content = f"{content}\n\n{SPOKEN_INSTRUCTIONS}"
    if now is not None and asks_time(question):
        hour = spanish_date(now).split(", ")[-1]
        content = f"{content}\n\n(Según el reloj de este computador, son las {hour})"
    messages.append(ChatMessage(role="user", content=content))
    return messages
