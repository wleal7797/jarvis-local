"""Worker de ingesta: procesa en segundo plano las tareas de la cola.

    .venv\\Scripts\\python -m worker            # modo normal: CPU con 4 hilos, prioridad baja
    .venv\\Scripts\\python -m worker --gpu      # modo noche: embeddings en la GPU (4x más rápido)
    .venv\\Scripts\\python -m worker --once     # procesa lo que haya en cola y termina

Por qué un proceso aparte: indexar puede tardar horas; si corriera dentro de la API,
el chat se volvería lento. Además corre con prioridad "debajo de lo normal", así
Windows siempre atiende primero lo que estés usando.
"""

import argparse
import asyncio
import contextlib
import logging
import re
import signal
from pathlib import Path

import httpx
import psutil

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.core.logging import setup_logging
from app.repositories import JobRepository
from app.services.embedding_service import OllamaEmbedder
from app.services.ingestion import IngestionService

logger = logging.getLogger("worker")


def lower_priority() -> None:
    process = psutil.Process()
    if hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS"):  # Windows
        process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    else:
        process.nice(10)


async def model_blob(http: httpx.AsyncClient, base_url: str, model: str) -> str | None:
    """Ruta del archivo del modelo en disco: identifica su proceso `llama-server`."""
    try:
        response = await http.post(f"{base_url}/api/show", json={"model": model})
        modelfile = response.json().get("modelfile", "")
    except (httpx.HTTPError, ValueError):
        return None
    match = re.search(r"^FROM (.+)$", modelfile, re.MULTILINE)
    return match.group(1).strip() if match else None


def lower_runner_priority(blob: str) -> int:
    """Ollama arranca sus procesos con prioridad "más alta de lo normal". El que calcula
    los embeddings para indexar se baja a "debajo de lo normal" para no frenar el PC."""
    lowered = 0
    below = getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", 10)
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if not (proc.info["name"] or "").lower().startswith("llama-server"):
                continue
            if blob in " ".join(proc.info["cmdline"] or []) and proc.nice() != below:
                proc.nice(below)
                lowered += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return lowered


async def keep_runner_low(blob: str | None, stop: asyncio.Event) -> None:
    """El proceso de Ollama puede reiniciarse (keep_alive): se revisa cada 5 s."""
    if not blob:
        return
    while not stop.is_set():
        if lower_runner_priority(blob):
            logger.info("prioridad de bge-m3 bajada para no frenar el PC")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=5)


async def unload_chat_model(http: httpx.AsyncClient, base_url: str, model: str) -> None:
    """En modo GPU se libera la VRAM del modelo de chat para que quepa bge-m3."""
    with contextlib.suppress(httpx.HTTPError):
        await http.post(f"{base_url}/api/generate", json={"model": model, "keep_alive": 0})


async def run(use_gpu: bool, once: bool, poll_seconds: float) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url())
    factory = create_session_factory(engine)
    service = IngestionService(
        factory,
        uploads_dir=Path(settings.uploads_dir),
        allow_internet=settings.ingestion_allow_internet,
    )
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # En Windows no existe: ahí Ctrl+C llega como KeyboardInterrupt (ver main()).
        with contextlib.suppress(NotImplementedError):
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)

    async with httpx.AsyncClient(timeout=600) as http:
        embedder = OllamaEmbedder(
            http,
            settings.ollama_base_url,
            settings.ollama_embed_model,
            use_gpu=use_gpu,
            threads=None if use_gpu else settings.ollama_embed_threads,
            keep_alive="10m" if use_gpu else settings.ollama_embed_keep_alive,
        )
        async with factory() as session:
            requeued = await JobRepository(session).requeue_stuck()
            await session.commit()
        if requeued:
            logger.info("tareas interrumpidas devueltas a la cola", extra={"jobs": requeued})
        logger.info("worker iniciado", extra={"modo": "GPU" if use_gpu else "CPU"})
        blob = await model_blob(http, settings.ollama_base_url, settings.ollama_embed_model)
        watcher = asyncio.create_task(keep_runner_low(blob, stop))

        while not stop.is_set():
            async with factory() as session:
                job = await JobRepository(session).claim_next()
                await session.commit()
            if job is None:
                if once:
                    break
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
                continue
            if use_gpu:
                await unload_chat_model(http, settings.ollama_base_url, settings.ollama_chat_model)
            logger.info("procesando tarea", extra={"job_id": job.id, "params": job.params})
            await service.process(job.id, embedder, http)
            logger.info("tarea terminada", extra={"job_id": job.id})
        stop.set()
        await watcher
    await engine.dispose()
    logger.info("worker detenido")


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker de ingesta de JARVIS")
    parser.add_argument("--gpu", action="store_true", help="embeddings en la GPU (modo noche)")
    parser.add_argument("--once", action="store_true", help="vaciar la cola y terminar")
    parser.add_argument("--poll", type=float, default=5.0, help="segundos entre revisiones")
    args = parser.parse_args()
    setup_logging(get_settings().log_level)
    lower_priority()
    try:
        asyncio.run(run(args.gpu, args.once, args.poll))
    except KeyboardInterrupt:
        logger.info("worker detenido con Ctrl+C")


if __name__ == "__main__":
    main()
