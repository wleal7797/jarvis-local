"""Mide si JARVIS trata de "usted" o tutea, con preguntas típicas de conversación.

    .venv\\Scripts\\python -m scripts.evaluate_style [modelo]   (por defecto jarvis:base)

Cuenta las respuestas con marcas de tuteo (tú, te, tu, puedes, contigo, ayudarte…).
"""

import json
import sys
import time

import httpx

PROMPTS = [
    "Hola Jarvis, ¿cómo estás?",
    "¿Qué puedes hacer por mí?",
    "Estoy cansado, dame un consejo.",
    "Recomiéndame una película para esta noche.",
    "¿Me ayudas a organizar mi día?",
    "Gracias por tu ayuda.",
    "Explícame qué es una base de datos.",
    "Cuéntame un chiste.",
    "No entendí lo que dijiste, repítelo más simple.",
    "¿Qué te dije hace un momento?",
    "¿Qué opinas del café colombiano?",
    "Tengo una reunión mañana y estoy nervioso.",
    "Buenas noches, me voy a dormir.",
]

from app.services.style_checks import tuteo_marks  # noqa: E402  (reglas compartidas, Etapa 12)


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "jarvis:base"
    tuteos = 0
    with httpx.Client(timeout=300) as client:
        for prompt in PROMPTS:
            started = time.perf_counter()
            reply = client.post(
                "http://127.0.0.1:11434/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "messages": [{"role": "user", "content": prompt}],
                },
            ).json()["message"]["content"]
            marks = tuteo_marks(reply)
            tuteos += bool(marks)
            flag = f"TUTEA {sorted(set(m.lower() for m in marks))}" if marks else "usted"
            print(f"[{flag}] ({time.perf_counter() - started:.1f}s) {prompt}\n    {reply.strip()}")
    print(json.dumps({"modelo": model, "respuestas": len(PROMPTS), "con_tuteo": tuteos}))


if __name__ == "__main__":
    main()
