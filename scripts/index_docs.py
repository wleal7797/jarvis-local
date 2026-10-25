"""Indexa la documentación del proyecto (README y docs/) como conocimiento de JARVIS.

Sirve como primer corpus real y como base de la evaluación del RAG. Si un archivo
cambió desde la última vez, se reemplaza su versión anterior.
    .venv\\Scripts\\python -m scripts.index_docs
"""

import asyncio
import time
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.services.embedding_service import OllamaEmbedder
from app.services.knowledge_service import KnowledgeService

SOURCE_NAME = "Documentación de JARVIS"
# Los informes de evaluación contienen las respuestas: no se indexan.
EXCLUDED = ("evaluacion",)


def doc_files() -> list[Path]:
    files = [Path("README.md"), *sorted(Path("docs").rglob("*.md"))]
    return [f for f in files if not any(word in f.name for word in EXCLUDED)]


def title_of(path: Path, text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url())
    factory = create_session_factory(engine)
    started = time.perf_counter()
    total_chunks = 0
    async with httpx.AsyncClient(timeout=600) as http:
        embedder = OllamaEmbedder(
            http,
            settings.ollama_base_url,
            settings.ollama_embed_model,
            use_gpu=settings.ollama_embed_on_gpu,
        )
        async with factory() as session:
            service = KnowledgeService(session, embedder)
            source = await service.get_or_create_source(
                "file", SOURCE_NAME, base_uri="docs/", license="Del proyecto"
            )
            for path in doc_files():
                text = path.read_text(encoding="utf-8")
                result = await service.add_text(
                    source, title_of(path, text), text, uri=path.as_posix()
                )
                await session.commit()
                total_chunks += result.chunks
                mark = "+" if result.created else "="
                print(f"{mark} {path.as_posix():55} {result.chunks:3} fragmentos")
    await engine.dispose()
    elapsed = time.perf_counter() - started
    print(f"Listo: {total_chunks} fragmentos nuevos en {elapsed:.1f} s")


if __name__ == "__main__":
    asyncio.run(main())
