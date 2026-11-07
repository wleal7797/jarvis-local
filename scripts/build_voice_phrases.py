r"""Genera las frases para grabar una voz propia (training/voz/frases.txt).

Las escribe el modelo local (Ollama, sin internet) por temas, con el estilo de JARVIS
(trato de usted, frases de mayordomo), y luego se filtran: entre 4 y 20 palabras, sin
números ni símbolos raros (se leen mal en voz alta), sin repetidas. Al final se revisa que
estén todos los sonidos del español.

    .venv\Scripts\python -m scripts.build_voice_phrases --objetivo 1200
"""

import argparse
import json
import re
import unicodedata
from pathlib import Path

import httpx

OUT = Path("training/voz/frases.txt")
TEMAS = [
    "saludos y despedidas de un mayordomo",
    "el clima y las estaciones",
    "recordatorios y citas",
    "la cocina y las recetas",
    "la música y el cine",
    "la salud y el descanso",
    "la ciencia y el espacio",
    "la historia antigua",
    "los animales y la naturaleza",
    "el hogar: luces, puertas y ventanas",
    "viajes y ciudades del mundo",
    "deportes",
    "libros y literatura",
    "tecnología y computadores",
    "el jardín y las plantas",
    "la familia y las celebraciones",
    "el trabajo y las reuniones",
    "el dinero y el ahorro, en general",
    "el mar y los ríos",
    "las montañas y los volcanes",
    "preguntas cortas que hace un asistente",
    "respuestas educadas de un asistente",
    "advertencias amables",
    "frases con humor fino",
    "el tiempo y las horas del día",
    "la noche y las estrellas",
    "el café y el desayuno",
    "la ropa y el estilo",
    "la seguridad de la casa",
    "los colores y las formas",
    "las emociones",
    "frases exclamativas de sorpresa",
    "preguntas de confirmación",
    "instrucciones paso a paso",
    "los idiomas y las palabras",
    "el arte y la pintura",
    "los inventos y los inventores",
    "los juegos y los pasatiempos",
    "la lluvia y las tormentas",
    "la paciencia y la calma",
]
SCHEMA = {
    "type": "object",
    "properties": {"frases": {"type": "array", "items": {"type": "string"}}},
    "required": ["frases"],
}
PROMPT = (
    "Escribe {n} frases distintas en español, sobre: {tema}. "
    "Las va a leer en voz alta una persona para grabar la voz de un asistente elegante "
    "(trata siempre de usted). Reglas: cada frase entre 5 y 18 palabras; sin números "
    "(escríbalos en letras); sin siglas, emojis, comillas ni paréntesis; variadas: "
    "afirmaciones, preguntas y exclamaciones; con palabras de todo tipo (incluya ll, ñ, rr, "
    "ch, x, z, güe). Responde sólo con el JSON."
)
OK_CHARS = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ,.;:¿?¡!\-]+$")


def plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", text)


def keep(frase: str) -> str | None:
    frase = re.sub(r"\s+", " ", frase.strip().strip('"').strip())
    if not OK_CHARS.match(frase):
        return None
    if not 4 <= len(frase.split()) <= 20:
        return None
    if frase[-1] not in ".?!":
        frase += "."
    return frase[0].upper() + frase[1:]


def coverage(frases: list[str]) -> dict[str, int]:
    text = " ".join(f.lower() for f in frases)
    sounds = ["ll", "ñ", "rr", "ch", "x", "z", "güe", "güi", "j", "ge", "gi", "qu", "y", "v", "h"]
    return {s: text.count(s) for s in sounds}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--objetivo", type=int, default=1200)
    parser.add_argument("--modelo", default="qwen3:4b-instruct")
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    args = parser.parse_args()

    frases: list[str] = []
    seen: set[str] = set()
    ronda = 0
    with httpx.Client(timeout=180) as client:
        while len(frases) < args.objetivo and ronda < 6:
            for tema in TEMAS:
                if len(frases) >= args.objetivo:
                    break
                body = {
                    "model": args.modelo,
                    "stream": False,
                    "format": SCHEMA,
                    "options": {"temperature": 0.9, "seed": ronda * 100 + TEMAS.index(tema)},
                    "messages": [{"role": "user", "content": PROMPT.format(n=35, tema=tema)}],
                }
                try:
                    content = client.post(f"{args.url}/api/chat", json=body).json()["message"][
                        "content"
                    ]
                    nuevas = json.loads(content)["frases"]
                except Exception as exc:  # una ronda fallida no detiene el resto
                    print("  falló", tema, exc)
                    continue
                for frase in nuevas:
                    frase = keep(str(frase))
                    if frase and plain(frase) not in seen:
                        seen.add(plain(frase))
                        frases.append(frase)
                print(f"ronda {ronda} · {tema}: {len(frases)}")
            ronda += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(frases[: args.objetivo]) + "\n", encoding="utf-8")
    total = min(len(frases), args.objetivo)
    words = sum(len(f.split()) for f in frases[:total])
    print(f"{total} frases · {words} palabras · ~{words / 150:.0f} min leyendo")
    print("sonidos:", coverage(frases[: args.objetivo]))


if __name__ == "__main__":
    main()
