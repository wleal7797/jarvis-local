"""Memoria de largo plazo: lo que JARVIS recuerda de lo que usted le cuenta.

Cómo aprende (después de responder, para no demorar la respuesta):
1. Filtro rápido: ¿la frase suena a un dato personal? ("me gusta…", "mi hija…",
   "recuerda que…"). Las preguntas, saludos y órdenes se descartan sin gastar GPU.
2. El modelo decide si vale la pena recordarlo y lo reescribe como una frase corta en
   tercera persona ("Le gusta el café sin azúcar."), con las fechas ya convertidas
   ("mañana" → "27 de octubre de 2026"). Responde un JSON con forma fija.
3. Si ya había un recuerdo casi igual (similitud ≥ 0,88), se reemplaza en vez de duplicarlo:
   "mi color favorito es el verde" corrige a "…es el azul".

Cómo lo usa: todos los recuerdos (los más importantes primero, hasta ~500 tokens) van al
principio de cada conversación. Como ese bloque cambia poco, Ollama lo deja en su caché y no
cuesta tiempo en cada pregunta. Con muchos recuerdos habría que elegirlos por parecido con
la pregunta (pgvector ya tiene el índice listo para eso).

La petición al modelo usa los mismos mensajes con los que empezará la siguiente pregunta
(recuerdos + historial): así la caché de Ollama sigue sirviendo para esa pregunta.
"""

import json
import logging
import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Memory
from app.repositories import ConversationRepository
from app.repositories.memory_repository import MemoryRepository
from app.services.embedding_service import Embedder
from app.services.llm import LLMError, LLMProvider
from app.services.prompt_builder import (
    MEMORY_TOKEN_BUDGET,
    build_messages,
    fit_memories,
    spanish_date,
)

logger = logging.getLogger(__name__)

HISTORY_MESSAGES = 20  # igual que ChatService: así el principio del mensaje coincide
DEDUPE_SIMILARITY = 0.88
# "¿En qué trabajo?" ↔ "Es ingeniero de sistemas.": ~0,5 con bge-m3.
RELEVANT_SIMILARITY = 0.45
MAX_MEMORY_CHARS = 300

# Palabras de primera persona o pedidos de recordar: sin ellas, no hay nada personal que guardar.
_PERSONAL = re.compile(
    r"\b(?:me|mi|mis|yo|soy|tengo|vivo|trabajo|estudio|prefiero|nac[ií]|cumplo|odio|amo|"
    r"adoro|quiero|necesito|recuerd[ae]|recu[eé]rdame|acu[eé]rdate|olvides|anota|apunta|"
    r"guarda|nuestr[oa]s?|estoy)\b",
    re.IGNORECASE,
)
_EXPLICIT = re.compile(r"\b(?:recuerd|recu[eé]rd|acu[eé]rd|no olvides|anota|apunta)", re.I)

EXTRACTION_PROMPT = (
    "(Tarea interna, no es parte de la conversación.)\n"
    "Anote SÓLO los datos duraderos que dice la FRASE de abajo sobre mí, mi familia o mi casa "
    "(nombres, gustos, aficiones, equipos, fechas importantes, salud, trabajo, dónde vivo, "
    "rutinas, mascotas) o lo que pedí que recordara. No repita lo que ya sabía de antes.\n"
    "- Cada dato debe entenderse solo: diga de quién habla. "
    '"Su perro se llama Rocky." (nunca "Se llama Rocky." si no es mi nombre).\n'
    "- Un dato por elemento, en una frase corta en tercera persona: "
    '"Se llama Andrés.", "Le gusta el café sin azúcar.", "Su hija se llama Ana.", '
    '"Es alérgico a las nueces." (nunca "Soy…", "Mi…", "Me…").\n'
    '- Hoy es {today}. Nunca escriba "hoy", "mañana" ni "el viernes": escriba la fecha '
    'exacta ("Debe comprar leche el martes 27 de octubre de 2026."). Cumpleaños y '
    'aniversarios, sin año ("Su hija cumple años el 3 de marzo.").\n'
    "- Si es un saludo, una pregunta, una orden para hacer ya o algo pasajero "
    '("tengo hambre", "estoy cansado"): "datos" vacío.\n'
    '- "importancia": 5 = nombres, fechas y salud; 3 = gustos y rutinas; 1 = detalles.\n'
    "- Sólo lo que dice esta frase; si dice un solo dato, devuelva un solo elemento.\n"
    "FRASE: «{text}»"
)

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "datos": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "dato": {"type": "string"},
                    "importancia": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["dato", "importancia"],
            },
        }
    },
    "required": ["datos"],
}


def is_personal_statement(text: str) -> bool:
    """ "Me gusta el café sin azúcar" → sí (no hace falta buscar en documentos)."""
    return worth_checking(text) and "?" not in text


def worth_checking(text: str) -> bool:
    """¿Vale la pena preguntarle al modelo si hay algo que recordar? (sin usar la GPU)"""
    clean = text.strip()
    if len(clean.split()) < 3:
        return False
    if _EXPLICIT.search(clean):  # "Recuerda que…", aunque venga con signos de pregunta
        return True
    if "?" in clean:
        return False
    return bool(_PERSONAL.search(clean))


@dataclass(frozen=True)
class Learned:
    memory_id: int
    content: str
    updated: bool  # True si corrigió un recuerdo que ya existía


class MemoryNotFoundError(LookupError):
    pass


class MemoryService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm: LLMProvider,
        embedder: Embedder,
        model: str,
        *,
        budget: int = MEMORY_TOKEN_BUDGET,
        dedupe_similarity: float = DEDUPE_SIMILARITY,
        clock: Callable[[], datetime] | None = None,
        learning: bool = True,
    ) -> None:
        self._learning = learning
        self._session_factory = session_factory
        self._llm = llm
        self._embedder = embedder
        self._model = model
        self._budget = budget
        self._dedupe = dedupe_similarity
        self._clock = clock or (lambda: datetime.now().astimezone())

    # ---------- Usar ----------

    async def facts_for_prompt(self, user_id: int) -> list[str]:
        async with self._session_factory() as session:
            memories = await MemoryRepository(session).list_for_user(user_id)
        return fit_memories([m.content for m in memories], self._budget)

    # ---------- Ver, corregir y borrar (panel "Memoria") ----------

    async def relevant(
        self, user_id: int, text: str, k: int = 3, min_similarity: float = RELEVANT_SIMILARITY
    ) -> list[str]:
        """Los recuerdos más parecidos a la pregunta (para ponerlos junto a los documentos)."""
        async with self._session_factory() as session:
            if not await MemoryRepository(session).exists_for(user_id):
                return []  # sin recuerdos no hace falta calcular el embedding
        vector = (await self._embedder.embed([text]))[0]
        async with self._session_factory() as session:
            found = await MemoryRepository(session).nearest(user_id, vector, k, min_similarity)
        return [memory.content for memory in found]

    async def all_for(self, user_id: int) -> Sequence[Memory]:
        async with self._session_factory() as session:
            return await MemoryRepository(session).list_for_user(user_id)

    async def add(
        self,
        user_id: int,
        content: str,
        importance: int = 3,
        source_message_id: int | None = None,
    ) -> Learned:
        """Guarda un recuerdo; si ya había uno casi igual, lo reemplaza."""
        content = _tidy(content)
        vector = (await self._embedder.embed([content]))[0]
        async with self._session_factory() as session:
            repo = MemoryRepository(session)
            similar = await repo.most_similar(user_id, vector)
            if similar is not None and similar[1] >= self._dedupe:
                memory = similar[0]
                memory.content = content
                memory.embedding = vector
                memory.importance = max(memory.importance, importance)
                updated = True
            else:
                memory = await repo.add(
                    Memory(
                        user_id=user_id,
                        content=content,
                        embedding=vector,
                        importance=importance,
                        source_message_id=source_message_id,
                    )
                )
                updated = False
            await session.commit()
            return Learned(memory_id=memory.id, content=memory.content, updated=updated)

    async def update(
        self, user_id: int, memory_id: int, content: str | None, importance: int | None
    ) -> Memory:
        vector = (await self._embedder.embed([_tidy(content)]))[0] if content else None
        async with self._session_factory() as session:
            memory = await MemoryRepository(session).get_for_user(memory_id, user_id)
            if memory is None:
                raise MemoryNotFoundError(memory_id)
            if content and vector is not None:
                memory.content = _tidy(content)
                memory.embedding = vector
            if importance is not None:
                memory.importance = importance
            await session.commit()
            await session.refresh(memory)
            return memory

    async def delete(self, user_id: int, memory_id: int) -> None:
        async with self._session_factory() as session:
            repo = MemoryRepository(session)
            memory = await repo.get_for_user(memory_id, user_id)
            if memory is None:
                raise MemoryNotFoundError(memory_id)
            await repo.delete(memory)
            await session.commit()

    # ---------- Aprender de la conversación ----------

    async def learn(self, user_id: int, reply_message_id: int) -> list[Learned]:
        """Revisa el mensaje que originó la respuesta `reply_message_id`. Nunca lanza
        errores: si algo falla, simplemente no aprende nada esta vez."""
        if not self._learning:
            return []
        try:
            return await self._learn(user_id, reply_message_id)
        except Exception as exc:
            logger.warning(
                "no se pudo revisar si había algo que recordar", extra={"error": str(exc)}
            )
            return []

    async def _learn(self, user_id: int, reply_message_id: int) -> list[Learned]:
        async with self._session_factory() as session:
            repo = ConversationRepository(session)
            reply = await repo.message_for_user(reply_message_id, user_id)
            if reply is None or reply.role != "assistant":
                return []
            history = await repo.recent_messages(reply.conversation_id, HISTORY_MESSAGES)
        said = next((m for m in reversed(history) if m.role == "user"), None)
        if said is None or not worth_checking(said.content):
            return []

        prompt = EXTRACTION_PROMPT.format(
            text=said.content.strip(), today=spanish_date(self._clock(), with_time=False)
        )
        # Igual que la siguiente pregunta (fecha + recuerdos + historial): la caché sirve.
        messages = build_messages(
            history, prompt, memories=await self.facts_for_prompt(user_id), now=self._clock()
        )
        try:
            raw = await self._llm.complete(
                messages,
                model=self._model,
                options={"temperature": 0, "num_predict": 200},
                json_schema=EXTRACTION_SCHEMA,
            )
        except LLMError as exc:
            logger.warning("el modelo no pudo revisar la frase", extra={"error": str(exc)})
            return []
        learned: list[Learned] = []
        for content, importance in _parse(raw):
            if not grounded(content, said.content):
                # El modelo a veces repite algo que ya sabía y que esta frase no dice.
                logger.info("dato descartado: no está en la frase", extra={"dato": content})
                continue
            item = await self.add(user_id, content, importance, source_message_id=said.id)
            logger.info(
                "recuerdo guardado", extra={"memory_id": item.memory_id, "updated": item.updated}
            )
            learned.append(item)
        return learned


# Palabras demasiado comunes para probar que un dato salió de la frase.
_COMMON = {
    "llama", "llamo", "llaman", "gusta", "gustan", "encanta", "tiene", "tengo", "tienen",
    "debe", "deben", "esta", "estoy", "este", "esto", "para", "como", "sobre", "cuando",
    "donde", "porque", "usuario", "persona", "favorito", "favorita", "prefiere", "prefiero",
    "siempre", "nunca", "mucho", "recuerda", "recuerde", "recordar", "recuerdame",
}  # fmt: skip


def _stems(text: str) -> set[str]:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z0-9]+", plain)
    return {w[:5] for w in words if (len(w) >= 4 or w.isdigit()) and w not in _COMMON}


def grounded(fact: str, said: str) -> bool:
    """¿El dato comparte alguna palabra con sentido con lo que dijo la persona?
    "Toby es un labrador" ← "Mi perro se llama Toby" sí; "Debe comprar leche" ← "Soy
    alérgico a las nueces" no (el modelo lo copió de lo que ya sabía)."""
    return bool(_stems(fact) & _stems(said))


# Si el modelo se olvida de la tercera persona: "Soy alérgico…" → "Es alérgico…".
_FIRST_PERSON = (
    (re.compile(r"^soy\b", re.I), "Es"),
    (re.compile(r"^estoy\b", re.I), "Está"),
    (re.compile(r"^tengo\b", re.I), "Tiene"),
    (re.compile(r"^vivo\b", re.I), "Vive"),
    (re.compile(r"^trabajo\b", re.I), "Trabaja"),
    (re.compile(r"^me\s+gusta", re.I), "Le gusta"),
    (re.compile(r"^me\s+llamo\b", re.I), "Se llama"),
    (re.compile(r"^mis\b", re.I), "Sus"),
    (re.compile(r"^mi\b", re.I), "Su"),
)


def _tidy(text: str) -> str:
    clean = " ".join(text.split())[:MAX_MEMORY_CHARS]
    for pattern, replacement in _FIRST_PERSON:
        clean = pattern.sub(replacement, clean, count=1)
    if clean and clean[-1] not in ".!?":
        clean += "."
    return clean[:1].upper() + clean[1:]


# "Mañana es martes 27…" no es un dato sobre la persona.
_ONLY_DATE = re.compile(r"^(?:hoy|ma[ñn]ana|ayer|pasado ma[ñn]ana)\s+(?:es|era|será)\b", re.I)
# "Está cansado hoy": un estado pasajero, no un recuerdo.
_PASSING = re.compile(
    r"\b(?:hoy|ahora|ahorita|en este momento)\b|\b(?:est[aá]|tiene)\s+(?:un poco\s+)?"
    r"(?:cansad|hambre|sueño|sed|aburrid|ocupad)",
    re.I,
)


def _parse(raw: str) -> list[tuple[str, int]]:
    """[(dato, importancia), …] desde el JSON del modelo; si viene mal, nada."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    items = data.get("datos") if isinstance(data, dict) else None
    found: list[tuple[str, int]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("dato") or "").strip()
        if len(content) < 5 or _ONLY_DATE.match(content) or _PASSING.search(content):
            continue
        try:
            importance = min(5, max(1, int(item.get("importancia", 3))))
        except (TypeError, ValueError):
            importance = 3
        found.append((content, importance))
    return found[:3]
