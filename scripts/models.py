"""Versiones del modelo de JARVIS (Etapa 12).

    .venv\\Scripts\\python -m scripts.models listar
    .venv\\Scripts\\python -m scripts.models importar models\\jarvis-v1.Q4_K_M.gguf --tag jarvis:v1
    .venv\\Scripts\\python -m scripts.models activar jarvis:v1
    .venv\\Scripts\\python -m scripts.models volver          (al que estaba activo antes)

Activar o volver se nota en la siguiente pregunta, sin reiniciar JARVIS.
"""

import argparse
import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.services.model_manager import ModelError, ModelManager


async def main() -> int:
    parser = argparse.ArgumentParser(description="Versiones del modelo de JARVIS")
    sub = parser.add_subparsers(dest="accion", required=True)
    sub.add_parser("listar", help="modelos registrados y cuál está activo")
    imp = sub.add_parser("importar", help="registrar un GGUF ajustado en Ollama")
    imp.add_argument("gguf", type=Path)
    imp.add_argument("--tag", default="jarvis:v1")
    imp.add_argument("--base", default="Qwen3-4B-Instruct-2507")
    imp.add_argument(
        "--plantilla", default="qwen3:4b-instruct", help="modelo de Ollama del que copiar el chat"
    )
    imp.add_argument("--notas", default="")
    act = sub.add_parser("activar", help="usar este modelo desde la siguiente pregunta")
    act.add_argument("tag")
    sub.add_parser("volver", help="volver al modelo que estaba activo antes")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(settings.database_url())
    manager = ModelManager(create_session_factory(engine), settings.ollama_base_url)
    try:
        if args.accion == "listar":
            for info in await manager.versions():
                mark = "●" if info.active else " "
                print(f" {mark} {info.tag:<22} {info.kind:<5} {info.notes or ''}")
        elif args.accion == "importar":
            version = await manager.import_gguf(
                args.gguf,
                args.tag,
                base_model=args.base,
                template_from=args.plantilla,
                notes=args.notas,
            )
            print(
                f"Registrado {version.ollama_tag}. Para usarlo: scripts.models activar {args.tag}"
            )
        elif args.accion == "activar":
            await manager.activate(args.tag)
            print(f"Activo: {args.tag} (desde la siguiente pregunta)")
        elif args.accion == "volver":
            print(f"Activo otra vez: {await manager.rollback()}")
        return 0
    except ModelError as exc:
        print(f"Error: {exc}")
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
