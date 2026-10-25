"""Arma la lista de mensajes que se envía al modelo.

La personalidad de JARVIS vive en `ollama/Modelfile` (mensaje de sistema del modelo).
Aquí se agrega lo que cambia en cada pregunta: el historial reciente y, desde la
Etapa 5, los fragmentos de conocimiento y los recuerdos del usuario.
"""

from collections.abc import Sequence

from app.models import Message
from app.services.llm import ChatMessage

# Presupuesto del historial dentro del contexto de 8192 tokens
# (ver docs/01-requisitos-de-hardware.md#longitud-de-contexto-8192-tokens).
HISTORY_TOKEN_BUDGET = 2400


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


def build_messages(history: Sequence[Message], question: str) -> list[ChatMessage]:
    messages = [ChatMessage(role=m.role, content=m.content) for m in trim_history(history)]  # type: ignore[arg-type]
    messages.append(ChatMessage(role="user", content=question))
    return messages
