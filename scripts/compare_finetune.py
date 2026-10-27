"""Compara el modelo base contra el ajustado con LoRA (Etapa 12).

    .venv\\Scripts\\python -m scripts.compare_finetune --nuevo jarvis:v1
    .venv\\Scripts\\python -m scripts.compare_finetune --base jarvis:base --nuevo jarvis:v1 --rapido

Mide con los MISMOS mensajes para los dos modelos:
1. **Estilo** con las preguntas de training/prompts/estilo_eval.txt (nunca se entrenaron):
   de usted, breves, sin citas inventadas ni emojis (app/services/style_checks.py).
2. **Precisión** con las preguntas del RAG (eval/rag_eval.jsonl, Etapa 5): ¿la respuesta
   trae el dato correcto usando los documentos? El ajuste no debe empeorarla.

"Terminado" (Etapa 12): el nuevo gana en estilo y no pierde precisión.
Resultado: docs/etapas/12-comparacion-modelos.md
"""

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.core.dependencies import retrieval_settings
from app.services.embedding_service import OllamaEmbedder
from app.services.llm import ChatMessage, OllamaProvider
from app.services.prompt_builder import build_messages, fit_context
from app.services.retrieval_service import RetrievalService
from app.services.style_checks import check
from scripts.build_style_dataset import EVAL_PROMPTS, read_prompts
from scripts.evaluate_rag import EVAL_FILE, contains_any

REPORT = Path("docs/etapas/12-comparacion-modelos.md")


async def ask(llm: OllamaProvider, model: str, messages: list[ChatMessage]) -> tuple[str, float]:
    started = time.perf_counter()
    answer = await llm.complete(
        messages, model=model, options={"temperature": 0, "seed": 7, "num_predict": 300}
    )
    return answer.strip(), time.perf_counter() - started


async def main() -> None:
    parser = argparse.ArgumentParser(description="Compara el modelo base contra el ajustado")
    parser.add_argument("--base", default="jarvis:base")
    parser.add_argument("--nuevo", required=True)
    parser.add_argument("--rapido", action="store_true", help="sólo 10 preguntas de cada tipo")
    parser.add_argument("--informe", type=Path, default=REPORT, help="dónde escribir el informe")
    args = parser.parse_args()
    models = [args.base, args.nuevo]

    settings = get_settings()
    style_prompts = read_prompts(EVAL_PROMPTS)
    rag_items = [
        json.loads(line)
        for line in EVAL_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rag_items = [i for i in rag_items if not i.get("negative")]
    if args.rapido:
        style_prompts, rag_items = style_prompts[:10], rag_items[:10]

    results: dict[str, dict] = {m: {"style": [], "rag": []} for m in models}
    engine = create_engine(settings.database_url())
    factory = create_session_factory(engine)
    async with httpx.AsyncClient(timeout=600) as http:
        llm = OllamaProvider(http, settings.ollama_base_url, args.base)
        embedder = OllamaEmbedder(http, settings.ollama_base_url, settings.ollama_embed_model)

        print(f"== Estilo ({len(style_prompts)} preguntas nuevas) ==")
        for prompt in style_prompts:
            for model in models:
                answer, seconds = await ask(llm, model, build_messages([], prompt))
                report = check(answer)
                results[model]["style"].append(
                    {
                        "prompt": prompt,
                        "answer": answer,
                        "s": seconds,
                        "problems": report.problems,
                        "words": report.words,
                        "tuteo": bool(report.tuteo),
                    }
                )
                verdict = "ok" if report.ok else "; ".join(report.problems)
                print(f"  {model:<14} {verdict:<30} {prompt}")

        print(f"\n== Precisión con documentos ({len(rag_items)} preguntas) ==")
        for item in rag_items:
            async with factory() as session:
                found = await RetrievalService(
                    session, embedder, retrieval_settings(settings)
                ).search(item["question"])
            messages = build_messages([], item["question"], fit_context(found))
            for model in models:
                answer, seconds = await ask(llm, model, messages)
                ok = contains_any(answer, item["keywords"])
                results[model]["rag"].append({"q": item["question"], "ok": ok, "s": seconds})
                print(f"  {model:<14} {'✅' if ok else '❌'} {item['question']}")
    await engine.dispose()
    write_report(results, models, args.rapido, args.informe)
    print(f"\nInforme: {args.informe}")


def summary(rows: dict) -> dict:
    style, rag = rows["style"], rows["rag"]
    return {
        "estilo_ok": sum(not r["problems"] for r in style),
        "usted": sum(not r["tuteo"] for r in style),
        "palabras": statistics.mean(r["words"] for r in style),
        "seg_estilo": statistics.mean(r["s"] for r in style),
        "precision": sum(r["ok"] for r in rag),
        "seg_rag": statistics.mean(r["s"] for r in rag),
        "n_style": len(style),
        "n_rag": len(rag),
    }


def write_report(results: dict, models: list[str], quick: bool, path: Path = REPORT) -> None:
    base, new = (summary(results[m]) for m in models)
    wins_style = new["estilo_ok"] > base["estilo_ok"]
    keeps_precision = new["precision"] >= base["precision"]
    verdict = (
        "✅ **El nuevo gana en estilo y no pierde precisión**: se puede activar."
        if wins_style and keeps_precision
        else "❌ **El nuevo no cumple** (debe ganar en estilo sin perder precisión): "
        "`jarvis:base` sigue activo."
    )
    lines = [
        "# Comparación · modelo base contra ajustado (Etapa 12)",
        "",
        "`python -m scripts.compare_finetune" + (" --rapido" if quick else "") + "` · "
        "temperatura 0, mismos mensajes para los dos.",
        "",
        f"| | `{models[0]}` | `{models[1]}` |",
        "|---|---|---|",
        f"| Estilo correcto | {base['estilo_ok']}/{base['n_style']} | "
        f"{new['estilo_ok']}/{new['n_style']} |",
        f"| Trata de usted | {base['usted']}/{base['n_style']} | {new['usted']}/{new['n_style']} |",
        f"| Palabras por respuesta | {base['palabras']:.0f} | {new['palabras']:.0f} |",
        f"| Precisión con documentos | {base['precision']}/{base['n_rag']} | "
        f"{new['precision']}/{new['n_rag']} |",
        f"| Segundos por respuesta (estilo) | {base['seg_estilo']:.1f} | {new['seg_estilo']:.1f} |",
        "",
        verdict,
        "",
        "## Respuestas con problemas de estilo",
        "",
    ]
    for model in models:
        bad = [r for r in results[model]["style"] if r["problems"]]
        lines.append(f"**`{model}`** ({len(bad)})")
        lines += [f"- *{r['prompt']}* → {', '.join(r['problems'])}" for r in bad] or ["- ninguna"]
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
