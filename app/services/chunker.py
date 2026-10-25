"""Divide documentos en fragmentos de ~500 tokens para indexarlos.

Por qué fragmentos y no documentos enteros:
- El modelo sólo tiene 8192 tokens de contexto: hay que darle lo justo.
- Un vector que resume 20 páginas no se parece a ninguna pregunta concreta.

Reglas:
- Respeta los títulos de Markdown (#, ##, ###): un fragmento no mezcla secciones.
- Cada fragmento empieza con su "ruta" (Documento > Sección > Subsección), así
  el fragmento se entiende solo y la búsqueda por palabras también encuentra los títulos.
- Entre fragmentos consecutivos de la misma sección se repite el último párrafo
  (solapamiento), para no cortar una idea a la mitad.
"""

import re
from dataclasses import dataclass, field

from app.services.prompt_builder import estimate_tokens

DEFAULT_MAX_TOKENS = 500
HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")


@dataclass
class TextChunk:
    text: str
    section: str
    token_count: int
    metadata: dict = field(default_factory=dict)


@dataclass
class _Section:
    path: list[str]
    paragraphs: list[str]


def _split_sections(text: str, title: str) -> list[_Section]:
    sections: list[_Section] = [_Section(path=[], paragraphs=[])]
    headings: list[str] = []
    buffer: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        if buffer:
            paragraph = "\n".join(buffer).strip()
            if paragraph:
                sections[-1].paragraphs.append(paragraph)
            buffer.clear()

    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            buffer.append(line)
            continue
        match = None if in_code else HEADING.match(line)
        if match:
            flush_paragraph()
            level = len(match.group(1))
            headings = headings[: level - 1] + [match.group(2).strip()]
            sections.append(_Section(path=list(headings), paragraphs=[]))
        elif not in_code and not line.strip():
            flush_paragraph()
        else:
            buffer.append(line)
    flush_paragraph()

    # El primer título de nivel 1 suele repetir el título del documento.
    for section in sections:
        if section.path and section.path[0].strip().lower() == title.strip().lower():
            section.path = section.path[1:]
    return [s for s in sections if s.paragraphs]


def _split_long_paragraph(paragraph: str, max_tokens: int) -> list[str]:
    """Un párrafo enorme (una tabla, un bloque de código) se corta por líneas."""
    if estimate_tokens(paragraph) <= max_tokens:
        return [paragraph]
    pieces: list[str] = []
    current: list[str] = []
    for line in paragraph.splitlines():
        if current and estimate_tokens("\n".join([*current, line])) > max_tokens:
            pieces.append("\n".join(current))
            current = []
        current.append(line[: max_tokens * 4])
    if current:
        pieces.append("\n".join(current))
    return pieces


def chunk_text(text: str, title: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for section in _split_sections(text, title):
        section_name = " > ".join(section.path)
        header = " > ".join([title, *section.path]) if title else section_name
        budget = max_tokens - estimate_tokens(header)

        paragraphs: list[str] = []
        for paragraph in section.paragraphs:
            paragraphs.extend(_split_long_paragraph(paragraph, budget))

        current: list[str] = []
        for paragraph in paragraphs:
            candidate = "\n\n".join([*current, paragraph])
            if current and estimate_tokens(candidate) > budget:
                chunks.append(_make_chunk(header, section_name, current))
                # Solapamiento: el último párrafo abre el siguiente fragmento si cabe.
                last = current[-1]
                fits = estimate_tokens(last) + estimate_tokens(paragraph) <= budget
                current = [last] if fits else []
            current.append(paragraph)
        if current:
            chunks.append(_make_chunk(header, section_name, current))
    return chunks


def _make_chunk(header: str, section: str, paragraphs: list[str]) -> TextChunk:
    body = "\n\n".join(paragraphs)
    text = f"{header}\n\n{body}" if header else body
    return TextChunk(text=text, section=section, token_count=estimate_tokens(text))
