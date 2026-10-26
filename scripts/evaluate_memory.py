"""Mide la memoria de JARVIS: ¿recuerda lo que se le cuenta y no guarda lo que no debe?

    .venv\\Scripts\\python -m scripts.evaluate_memory

Con la API encendida (.\\scripts\\jarvis.ps1 iniciar):
1. En una conversación le cuenta 10 datos personales y le dice 8 cosas que NO son datos
   (preguntas, órdenes, saludos, estados pasajeros).
2. En una conversación NUEVA le pregunta por cada dato y revisa la respuesta.
3. Al final borra los recuerdos y las conversaciones que creó: sus datos reales no se tocan.

Resultados en docs/etapas/10-evaluacion-memoria.md.
"""

import json
import sys
import time
import unicodedata

import httpx

API = "http://127.0.0.1:8000"

# (lo que se cuenta, la pregunta en otra conversación, palabras que deben aparecer)
FACTS = [
    ("Me llamo Camilo.", "¿Cómo me llamo?", ["camilo"]),
    ("Mi esposa se llama Laura.", "¿Cómo se llama mi esposa?", ["laura"]),
    ("Mi perro se llama Rocky y es un beagle.", "¿Qué raza es mi perro?", ["beagle"]),
    ("Soy alérgico a los mariscos.", "¿A qué soy alérgico?", ["marisco"]),
    ("Me gusta el café sin azúcar.", "¿Cómo me gusta el café?", ["azucar"]),
    ("Mi cumpleaños es el 14 de agosto.", "¿Cuándo es mi cumpleaños?", ["14", "agosto"]),
    ("Trabajo como ingeniero de sistemas.", "¿En qué trabajo?", ["ingenier"]),
    ("Vivo en Chía, cerca de Bogotá.", "¿En qué municipio vivo?", ["chia"]),
    ("Recuerda que el plomero viene el jueves.", "¿Quién viene el jueves?", ["plomero"]),
    ("Mi equipo de fútbol es Millonarios.", "¿De qué equipo de fútbol soy?", ["millonarios"]),
]
NOT_FACTS = [
    "Hola Jarvis, buenos días.",
    "¿Cuál es la capital de Australia?",
    "Pon música tranquila, por favor.",
    "Tengo hambre.",
    "Estoy un poco cansado hoy.",
    "Gracias, eso es todo.",
    "Explícame qué es la fotosíntesis en una frase.",
    "¿Qué hora es?",
]


def plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def say(client: httpx.Client, text: str, conversation_id: int | None):
    started = time.perf_counter()
    answer, learned, cid = [], [], conversation_id
    with client.stream(
        "POST", "/api/chat", json={"message": text, "conversation_id": conversation_id}
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            event = json.loads(line)
            if event["type"] == "start":
                cid = event["conversation_id"]
            elif event["type"] == "token":
                answer.append(event["content"])
            elif event["type"] == "memory":
                learned.append(event["content"])
    return cid, "".join(answer).strip(), learned, time.perf_counter() - started


def main() -> int:
    client = httpx.Client(base_url=API, timeout=300)
    try:
        before = {m["id"] for m in client.get("/api/memories").json()}
    except httpx.HTTPError:
        print("La API no responde. Enciéndala: .\\scripts\\jarvis.ps1 iniciar")
        return 1
    conversations: list[int] = []

    try:
        print("== 1. Contarle cosas ==")
        cid = None
        stored, false_memories = 0, []
        for text, _, _ in FACTS:
            cid, _, learned, _ = say(client, text, cid)
            stored += bool(learned)
            print(f"{'✅' if learned else '❌'} {text}  →  {' | '.join(learned) or '(nada)'}")
        for text in NOT_FACTS:
            cid, _, learned, _ = say(client, text, cid)
            if learned:
                false_memories.append((text, learned))
            print(f"{'❌' if learned else '✅'} {text}  →  {' | '.join(learned) or '(nada)'}")
        conversations.append(cid)

        print("\n== 2. Preguntar en una conversación nueva ==")
        cid, recalled, times = None, 0, []
        for _, question, words in FACTS:
            cid, answer, _, took = say(client, question, cid)
            ok = all(w in plain(answer) for w in words)
            recalled += ok
            times.append(took)
            print(f"{'✅' if ok else '❌'} {question}  →  {answer[:110]}  ({took:.1f} s)")
        conversations.append(cid)

        print("\n== Resultado ==")
        print(f"Datos guardados:      {stored}/{len(FACTS)}")
        print(f"Recordados después:   {recalled}/{len(FACTS)}")
        print(f"Falsos recuerdos:     {len(false_memories)}/{len(NOT_FACTS)}")
        print(f"Tiempo medio por pregunta: {sum(times) / len(times):.1f} s")
        return 0
    finally:
        created = [m["id"] for m in client.get("/api/memories").json() if m["id"] not in before]
        for memory_id in created:
            client.delete(f"/api/memories/{memory_id}")
        for conversation_id in conversations:
            if conversation_id:
                client.delete(f"/api/conversations/{conversation_id}")
        print(
            f"(Limpieza: {len(created)} recuerdos y {len(conversations)} conversaciones borrados)"
        )


if __name__ == "__main__":
    sys.exit(main())
