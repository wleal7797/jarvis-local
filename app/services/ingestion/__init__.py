"""Ingesta de conocimiento: cargadores (archivos, web, Wikipedia) y cola de tareas."""

from app.services.ingestion.base import DocumentLoader, LoaderError, RawDocument
from app.services.ingestion.file_loader import FileLoader
from app.services.ingestion.ingestion_service import IngestionError, IngestionService
from app.services.ingestion.web_loader import WebLoader
from app.services.ingestion.wikipedia_loader import WikipediaLoader

__all__ = [
    "DocumentLoader",
    "FileLoader",
    "IngestionError",
    "IngestionService",
    "LoaderError",
    "RawDocument",
    "WebLoader",
    "WikipediaLoader",
]
