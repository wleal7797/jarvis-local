"""¿Una respuesta tiene el estilo de JARVIS? (Etapa 12)

Se usa para dos cosas:
- Elegir qué respuestas del modelo actual sirven para entrenar el nuevo (sólo las buenas).
- Comparar el modelo base contra el ajustado.

Reglas: trata de "usted", es breve, no inventa citas [n] sin documentos, sin emojis ni
listas largas (las respuestas se escuchan en voz alta).
"""

import re
from dataclasses import dataclass

# Formas de tú dirigidas al usuario. "te"/"tu" sueltos son la señal más común.
TUTEO = re.compile(
    r"\b(tú|tu|tus|te|ti|contigo|tienes|puedes|quieres|necesitas|sabes|eres|estás|"
    r"prefieres|deseas|dime|cuéntame|recuerda|intenta|haz|toma|"
    r"\w+(?:arte|erte|irte))\b",
    re.IGNORECASE,
)
# Palabras que terminan como "-arte/-erte/-irte" pero no tutean.
FALSE_POSITIVES = {
    "parte", "arte", "suerte", "fuerte", "muerte", "norte", "corte", "aparte", "deporte",
    "transporte", "soporte", "importe", "monte", "frente", "gente", "mente", "diente",
    "puente", "fuente", "baluarte", "estandarte", "descarte", "reparte", "comparte",
}  # fmt: skip
CITATION = re.compile(r"\[\d{1,2}\]")
EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")
LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s", re.MULTILINE)
THINKING = re.compile(r"</?think>", re.IGNORECASE)

MAX_WORDS = 120


def tuteo_marks(text: str) -> list[str]:
    return [m for m in TUTEO.findall(text) if m.lower() not in FALSE_POSITIVES]


@dataclass(frozen=True)
class StyleReport:
    words: int
    tuteo: list[str]
    citations: bool
    emojis: bool
    list_items: int
    thinking: bool

    @property
    def problems(self) -> list[str]:
        found = []
        if self.tuteo:
            found.append("tutea: " + ", ".join(sorted({m.lower() for m in self.tuteo})))
        if self.citations:
            found.append("cita [n] sin documentos")
        if self.emojis:
            found.append("emojis")
        if self.list_items > 3:
            found.append("lista larga")
        if self.words > MAX_WORDS:
            found.append(f"larga ({self.words} palabras)")
        if self.words < 2:
            found.append("vacía")
        if self.thinking:
            found.append("razonamiento visible")
        return found

    @property
    def ok(self) -> bool:
        return not self.problems


def check(answer: str, *, with_documents: bool = False) -> StyleReport:
    """Revisa una respuesta. Con documentos, las citas [n] sí están permitidas."""
    return StyleReport(
        words=len(answer.split()),
        tuteo=tuteo_marks(answer),
        citations=bool(CITATION.search(answer)) and not with_documents,
        emojis=bool(EMOJI.search(answer)),
        list_items=len(LIST_ITEM.findall(answer)),
        thinking=bool(THINKING.search(answer)),
    )
