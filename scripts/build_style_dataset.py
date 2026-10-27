"""Genera el dataset de estilo de JARVIS (Etapa 12) con el modelo actual como "profesor".

    .venv\\Scripts\\python -m scripts.build_style_dataset            (todas las preguntas)
    .venv\\Scripts\\python -m scripts.build_style_dataset --limite 20 (prueba corta)

1. Toma las preguntas genéricas de training/prompts/estilo.txt (sin datos personales).
2. jarvis:base responde cada una 2 veces (con un poco de variedad).
3. Sólo se guardan las respuestas con buen estilo (app/services/style_checks.py):
   de usted, breves, sin citas inventadas, sin emojis ni listas largas.
4. Quedan en la base como el dataset "estilo-jarvis" (público: se puede entrenar en Colab).

Se puede cortar y volver a ejecutar: salta las preguntas que ya tienen respuesta.
Tarda ~5 s por pregunta en la GTX 1650 Ti (~15 min para todas).
"""

import argparse
import asyncio
import time
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.services.dataset_service import DatasetService, Example
from app.services.llm import ChatMessage, LLMError, OllamaProvider
from app.services.style_checks import check

PROMPTS = Path("training/prompts/estilo.txt")
EVAL_PROMPTS = Path("training/prompts/estilo_eval.txt")
DATASET = "estilo-jarvis"
DESCRIPTION = (
    "Respuestas de jarvis:base a preguntas genéricas, filtradas por estilo "
    "(usted, breves, sin citas ni emojis). Sin datos personales."
)
SAMPLES = 2


def read_prompts(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Genera el dataset de estilo de JARVIS")
    parser.add_argument("--limite", type=int, default=0, help="sólo las primeras N preguntas")
    parser.add_argument("--modelo", default=None, help="modelo profesor (por defecto el de .env)")
    args = parser.parse_args()

    settings = get_settings()
    model = args.modelo or settings.ollama_chat_model
    prompts = read_prompts(PROMPTS)
    held_out = {p.lower() for p in read_prompts(EVAL_PROMPTS)}
    leaked = [p for p in prompts if p.lower() in held_out]
    if leaked:  # la comparación sólo es justa si las de evaluación nunca se entrenan
        raise SystemExit(f"Estas preguntas también están en la evaluación: {leaked}")
    if args.limite:
        prompts = prompts[: args.limite]

    engine = create_engine(settings.database_url())
    service = DatasetService(create_session_factory(engine))
    done = await service.prompts_in(DATASET)
    pending = [p for p in prompts if p not in done]
    print(f"{len(prompts)} preguntas · {len(prompts) - len(pending)} ya hechas · modelo {model}")

    kept = rejected = 0
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=300) as http:
        llm = OllamaProvider(http, settings.ollama_base_url, model)
        for n, prompt in enumerate(pending, 1):
            good: list[Example] = []
            for sample in range(SAMPLES):
                try:
                    answer = await llm.complete(
                        [ChatMessage(role="user", content=prompt)],
                        options={"temperature": 0.7, "seed": 1000 + sample, "num_predict": 250},
                    )
                except LLMError as exc:
                    print(f"   ! {exc}")
                    continue
                answer = answer.strip()
                report = check(answer)
                if report.ok:
                    good.append(Example(user_prompt=prompt, assistant_answer=answer))
                    kept += 1
                else:
                    rejected += 1
                    print(f"   descartada ({'; '.join(report.problems)}): {prompt}")
            await service.add(DATASET, DESCRIPTION, personal=False, examples=good)
            elapsed = time.perf_counter() - started
            print(
                f"[{n}/{len(pending)}] {len(good)}/{SAMPLES} "
                f"· {elapsed / n:.1f} s/pregunta · {prompt}"
            )

    total = next((d for d in await service.overview() if d.name == DATASET), None)
    await engine.dispose()
    print(f"\nGuardadas {kept}, descartadas {rejected}.")
    if total:
        print(f"Dataset '{DATASET}': {total.examples} ejemplos.")


if __name__ == "__main__":
    asyncio.run(main())
