"""Arma la lista de mensajes que se envía al modelo.

La personalidad de JARVIS vive en `ollama/Modelfile` (mensaje de sistema del modelo).
Aquí se agrega lo que cambia en cada pregunta:
- el historial reciente de la conversación, y
- los fragmentos de conocimiento recuperados (RAG), numerados para poder citarlos.

Importante: el contexto va DENTRO del mensaje del usuario y no como mensaje "system".
Ollama sólo antepone el SYSTEM del Modelfile cuando el primer mensaje no es de sistema;
si mandáramos uno propio, JARVIS perdería su personalidad.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.models import Message
from app.services.llm import ChatMessage

if TYPE_CHECKING:
    from app.services.retrieval_service import RetrievedChunk

# Reparto del contexto de 8192 tokens
# (ver docs/01-requisitos-de-hardware.md#longitud-de-contexto-8192-tokens).
HISTORY_TOKEN_BUDGET = 2400
# 3 fragmentos de ~500 tokens: cada 250 tokens de contexto cuestan ~1 s en la GTX 1650 Ti.
CONTEXT_TOKEN_BUDGET = 1800

CONTEXT_INSTRUCTIONS = (
    "Instrucciones para responder:\n"
    "- Si la información de arriba responde la pregunta, básate en ella y cita la fuente "
    "con su número entre corchetes, por ejemplo [1] o [2].\n"
    "- Si no la responde, dilo con sinceridad y, si sabes la respuesta por tu conocimiento "
    "general, aclara que no viene de los documentos.\n"
    "- No inventes números de fuente ni datos que no estén en la información."
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


def format_context(chunks: Sequence["RetrievedChunk"]) -> str:
    blocks = []
    for number, chunk in enumerate(chunks, start=1):
        label = " — ".join(part for part in (chunk.title, chunk.section) if part)
        blocks.append(f"[{number}] {label}\n{chunk.content}")
    return (
        "Información encontrada en los documentos de esta casa:\n\n"
        + "\n\n---\n\n".join(blocks)
        + "\n\n"
        + CONTEXT_INSTRUCTIONS
    )


def build_messages(
    history: Sequence[Message],
    question: str,
    context: Sequence["RetrievedChunk"] = (),
) -> list[ChatMessage]:
    messages = [ChatMessage(role=m.role, content=m.content) for m in trim_history(history)]  # type: ignore[arg-type]
    content = f"{format_context(context)}\n\nPregunta: {question}" if context else question
    messages.append(ChatMessage(role="user", content=content))
    return messages
