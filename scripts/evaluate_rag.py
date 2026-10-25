"""Evalúa el RAG con preguntas cuya respuesta está en la documentación del proyecto.

Mide, para cada pregunta de eval/rag_eval.jsonl:
- Búsqueda: ¿algún fragmento recuperado contiene la respuesta? ¿en qué posición?
- Respuesta CON RAG y SIN RAG: ¿la respuesta contiene el dato correcto?
- Citas: ¿JARVIS citó la fuente con [n]?
- Preguntas "negativas" (charla o cultura general): no deberían traer contexto.

    .venv\\Scripts\\python -m scripts.evaluate_rag
Resultado: docs/etapas/05-evaluacion-rag.md
"""

import asyncio
import json
import re
import statistics
import time
import unicodedata
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.core.dependencies import retrieval_settings
from app.repositories import ChunkRepository
from app.services.embedding_service import OllamaEmbedder
from app.services.llm import OllamaProvider
from app.services.prompt_builder import build_messages, fit_context
from app.services.retrieval_service import RetrievalService

EVAL_FILE = Path("eval/rag_eval.jsonl")
REPORT = Path("docs/etapas/05-evaluacion-rag.md")
RESULTS = Path("eval/resultados.json")
CITATION = re.compile(r"\[\d{1,2}\]")


def normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", plain)


def contains_any(text: str, keywords: list[str]) -> bool:
    haystack = normalize(text)
    return any(normalize(k) in haystack for k in keywords)


async def generate(llm: OllamaProvider, messages) -> tuple[str, float]:
    started = time.perf_counter()
    parts = [c.content async for c in llm.chat_stream(messages, options={"temperature": 0})]
    return "".join(parts).strip(), time.perf_counter() - started


async def main() -> None:
    settings = get_settings()
    items = [json.loads(line) for line in EVAL_FILE.read_text(encoding="utf-8").splitlines()]
    engine = create_engine(settings.database_url())
    factory = create_session_factory(engine)
    results = []
    async with httpx.AsyncClient(timeout=600) as http:
        embedder = OllamaEmbedder(http, settings.ollama_base_url, settings.ollama_embed_model)
        llm = OllamaProvider(http, settings.ollama_base_url, settings.ollama_chat_model)
        for item in items:
            question, keywords = item["question"], item["keywords"]
            negative = item.get("negative", False)
            async with factory() as session:
                t0 = time.perf_counter()
                found = await RetrievalService(
                    session, embedder, retrieval_settings(settings)
                ).search(question)
                retrieval_s = time.perf_counter() - t0
                top = await ChunkRepository(session).nearest(
                    await embedder.embed_one(question), k=1
                )
            context = fit_context(found)
            rank = next(
                (i for i, c in enumerate(context, 1) if contains_any(c.content, keywords)), None
            )
            rag_answer, rag_s = await generate(llm, build_messages([], question, context))
            row = {
                "id": item["id"],
                "question": question,
                "negative": negative,
                "top_similarity": round(top[0].similarity, 3) if top else None,
                "context": len(context),
                "hit_rank": rank,
                "retrieval_s": round(retrieval_s, 2),
                "rag_answer": rag_answer,
                "rag_ok": contains_any(rag_answer, keywords) if keywords else None,
                "rag_s": round(rag_s, 2),
                "cited": bool(CITATION.search(rag_answer)),
            }
            if not negative:
                plain_answer, _ = await generate(llm, build_messages([], question))
                row["plain_answer"] = plain_answer
                row["plain_ok"] = contains_any(plain_answer, keywords)
            results.append(row)
            print(
                f"{item['id']!s:>4} rank={rank!s:4} sim={row['top_similarity']} "
                f"rag={row['rag_ok']} plain={row.get('plain_ok')}"
            )
    await engine.dispose()
    RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(results, settings)


def pct(n: int, total: int) -> str:
    return f"{100 * n / total:.0f} %" if total else "—"


def write_report(results: list[dict], settings) -> None:
    pos = [r for r in results if not r["negative"]]
    neg = [r for r in results if r["negative"]]
    n = len(pos)
    hit1 = sum(1 for r in pos if r["hit_rank"] == 1)
    hitk = sum(1 for r in pos if r["hit_rank"])
    mrr = sum(1 / r["hit_rank"] for r in pos if r["hit_rank"]) / n
    rag_ok = sum(1 for r in pos if r["rag_ok"])
    plain_ok = sum(1 for r in pos if r["plain_ok"])
    cited = sum(1 for r in pos if r["cited"])
    neg_clean = sum(1 for r in neg if r["context"] == 0)
    pos_sims = [r["top_similarity"] for r in pos if r["top_similarity"] is not None]
    neg_sims = [r["top_similarity"] for r in neg if r["top_similarity"] is not None]

    lines = [
        "# Evaluación del RAG (generado por `scripts/evaluate_rag.py`)",
        "",
        f"Corpus: documentación del proyecto · Modelo: `{settings.ollama_chat_model}` · "
        f"Embeddings: `{settings.ollama_embed_model}` · top_k={settings.rag_top_k} · "
        f"similitud mínima {settings.rag_min_similarity} "
        f"(con palabras clave {settings.rag_min_similarity_with_keywords}) · temperatura 0",
        "",
        "## Resumen",
        "",
        "| Métrica | Resultado |",
        "|---|---|",
        f"| La respuesta está en el 1.er fragmento (hit@1) | {hit1}/{n} ({pct(hit1, n)}) |",
        f"| La respuesta está entre los fragmentos (hit@{settings.rag_top_k}) | "
        f"{hitk}/{n} ({pct(hitk, n)}) |",
        f"| MRR (posición media inversa) | {mrr:.2f} |",
        f"| **Respuesta correcta CON RAG** | **{rag_ok}/{n} ({pct(rag_ok, n)})** |",
        f"| Respuesta correcta SIN RAG | {plain_ok}/{n} ({pct(plain_ok, n)}) |",
        f"| Respuestas con cita [n] | {cited}/{n} ({pct(cited, n)}) |",
        f"| Preguntas fuera de tema sin contexto (correcto) | "
        f"{neg_clean}/{len(neg)} ({pct(neg_clean, len(neg))}) |",
        f"| Similitud del mejor fragmento: preguntas del corpus | "
        f"mín {min(pos_sims):.2f} · mediana {statistics.median(pos_sims):.2f} |",
        f"| Similitud del mejor fragmento: preguntas fuera de tema | "
        f"máx {max(neg_sims):.2f} · mediana {statistics.median(neg_sims):.2f} |",
        f"| Tiempo medio de búsqueda | "
        f"{statistics.mean(r['retrieval_s'] for r in results):.2f} s |",
        f"| Tiempo medio de respuesta con RAG | {statistics.mean(r['rag_s'] for r in pos):.1f} s |",
        "",
        "## Detalle por pregunta",
        "",
        "| # | Pregunta | Posición | Similitud | Con RAG | Sin RAG | Cita |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in pos:
        lines.append(
            f"| {r['id']} | {r['question']} | {r['hit_rank'] or '—'} | {r['top_similarity']} | "
            f"{'✅' if r['rag_ok'] else '❌'} | {'✅' if r['plain_ok'] else '❌'} | "
            f"{'✅' if r['cited'] else '—'} |"
        )
    lines += [
        "",
        "## Preguntas fuera de tema",
        "",
        "| Pregunta | Similitud | Fragmentos usados |",
        "|---|---|---|",
    ]
    for r in neg:
        lines.append(f"| {r['question']} | {r['top_similarity']} | {r['context']} |")
    lines += ["", "## Respuestas que fallaron con RAG", ""]
    for r in pos:
        if not r["rag_ok"]:
            answer = r["rag_answer"].replace("\n", " ")
            lines += [f"**{r['id']}. {r['question']}**", "", f"> {answer}", ""]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Informe: {REPORT}")


if __name__ == "__main__":
    asyncio.run(main())
