"""Compara modelos de Ollama con las mismas preguntas y la misma personalidad.

Mide velocidad y uso de GPU, y guarda las respuestas para evaluarlas a mano.
    .venv\\Scripts\\python -m scripts.compare_models
Resultado: docs/etapas/03-comparacion-modelos-datos.md
"""

import json
import re
import subprocess
import time
from pathlib import Path

import httpx

OLLAMA = "http://127.0.0.1:11434"
MODELFILE = Path("ollama/Modelfile")
OUTPUT = Path("docs/etapas/03-comparacion-modelos-datos.md")

# (modelo, opciones extra de la petición)
MODELS: list[tuple[str, dict]] = [
    ("qwen3:4b-instruct", {}),
    ("qwen3:4b", {"think": False}),
    ("llama3.2:latest", {}),
    ("qwen2.5:3b", {}),
]

QUESTIONS = [
    ("Dato histórico", "¿En qué año se fundó Bogotá y quién la fundó?"),
    (
        "Razonamiento",
        "Tengo 3 cajas con 12 huevos cada una. Se rompen 5 y regalo la mitad de los que "
        "quedan. ¿Cuántos huevos me quedan?",
    ),
    ("Honestidad", "¿Cuál es el número de teléfono de mi vecino Carlos?"),
    ("Instrucciones", "Explícame qué es la fotosíntesis en una sola frase."),
    ("Estilo y capacidades", "Buenas noches JARVIS, ¿me puedes poner música?"),
]


def system_prompt() -> str:
    """La personalidad de JARVIS, tomada del Modelfile para usar la misma en todos."""
    match = re.search(r'SYSTEM """(.*?)"""', MODELFILE.read_text(encoding="utf-8"), re.S)
    assert match, "No se encontró SYSTEM en el Modelfile"
    return match.group(1).strip()


def gpu_split(model: str) -> str:
    out = subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith(model):
            found = re.search(r"(\d+% GPU|\d+%/\d+% CPU/GPU|100% CPU)", line)
            return found.group(1) if found else "?"
    return "?"


def ask(client: httpx.Client, model: str, extra: dict, system: str, question: str) -> dict:
    payload = {
        "model": model,
        "stream": True,
        "options": {"temperature": 0.6, "num_ctx": 8192},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        **extra,
    }
    start = time.perf_counter()
    first_token = None
    text = ""
    final: dict = {}
    with client.stream("POST", f"{OLLAMA}/api/chat", json=payload) as response:
        for line in response.iter_lines():
            data = json.loads(line)
            piece = data.get("message", {}).get("content", "")
            if piece and first_token is None:
                first_token = time.perf_counter() - start
            text += piece
            if data.get("done"):
                final = data
    eval_s = final.get("eval_duration", 0) / 1e9
    speed = final["eval_count"] / eval_s if eval_s else 0
    return {
        "answer": text.strip(),
        "first_token_s": round(first_token or 0, 2),
        "total_s": round(time.perf_counter() - start, 2),
        "tokens_per_second": round(speed, 1),
        "load_s": round(final.get("load_duration", 0) / 1e9, 2),
    }


def main() -> None:
    system = system_prompt()
    lines = [
        "# Datos de la comparación de modelos (generado por `scripts/compare_models.py`)",
        "",
        "Misma personalidad (SYSTEM del Modelfile), temperatura 0,6 y contexto 8192.",
        "",
    ]
    summary = [
        "| Modelo | Carga | GPU | Velocidad media | Primera palabra media |",
        "|---|---|---|---|---|",
    ]
    with httpx.Client(timeout=600) as client:
        for model, extra in MODELS:
            print(f"== {model}")
            results = []
            for topic, question in QUESTIONS:
                result = ask(client, model, extra, system, question)
                results.append((topic, question, result))
                print(f"   {topic}: {result['tokens_per_second']} tok/s")
            split = gpu_split(model)
            subprocess.run(["ollama", "stop", model], capture_output=True)
            measured = [r for _, _, r in results[1:]]  # la primera incluye la carga
            avg_speed = sum(r["tokens_per_second"] for r in measured) / len(measured)
            avg_first = sum(r["first_token_s"] for r in measured) / len(measured)
            summary.append(
                f"| `{model}` | {results[0][2]['load_s']} s | {split} | "
                f"{avg_speed:.1f} tok/s | {avg_first:.2f} s |"
            )
            lines += [f"## `{model}`", ""]
            for topic, question, result in results:
                lines += [
                    f"**{topic}:** {question}",
                    "",
                    f"> {result['answer'].replace(chr(10), chr(10) + '> ')}",
                    "",
                    f"*{result['tokens_per_second']} tok/s · primera palabra "
                    f"{result['first_token_s']} s · total {result['total_s']} s*",
                    "",
                ]
    OUTPUT.write_text("\n".join(lines[:4] + summary + [""] + lines[4:]), encoding="utf-8")
    print(f"Guardado en {OUTPUT}")


if __name__ == "__main__":
    main()
