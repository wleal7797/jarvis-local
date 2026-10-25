"""Descarga páginas web y extrae su texto principal con trafilatura.

Buenas prácticas incluidas:
- Respeta `robots.txt` (si un sitio pide no ser leído por robots, no se lee).
- Espera entre páginas para no saturar el sitio.
- Se identifica con un User-Agent honesto.
- Sólo sigue enlaces del mismo dominio y hasta `max_pages` páginas.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura

from app.services.ingestion.base import USER_AGENT, LoaderError, RawDocument

logger = logging.getLogger(__name__)

LINK = re.compile(r"""href=["']([^"'#]+)""", re.IGNORECASE)
SKIP_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".pdf",
    ".zip",
    ".mp4",
    ".mp3",
    ".css",
    ".js",
)
MAX_PAGES_LIMIT = 50


class WebLoader:
    def __init__(
        self,
        http: httpx.AsyncClient,
        url: str,
        *,
        max_pages: int = 1,
        delay_seconds: float = 1.0,
    ) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise LoaderError("La dirección debe empezar por http:// o https://")
        self._http = http
        self._start = url
        self._domain = parsed.netloc
        self._max_pages = max(1, min(max_pages, MAX_PAGES_LIMIT))
        self._delay = delay_seconds
        self._robots: RobotFileParser | None = None

    async def load(self) -> AsyncIterator[RawDocument]:
        await self._load_robots()
        queue = [self._start]
        seen: set[str] = set()
        loaded = 0
        while queue and loaded < self._max_pages:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            if not self._allowed(url):
                logger.info("robots.txt no permite leer esta página", extra={"url": url})
                continue
            html = await self._fetch(url)
            if html is None:
                continue
            document = self._extract(url, html)
            if document is not None:
                loaded += 1
                yield document
            if loaded < self._max_pages:
                queue.extend(u for u in self._links(url, html) if u not in seen)
                await asyncio.sleep(self._delay)
        if loaded == 0:
            raise LoaderError(f"No se pudo extraer texto de {self._start}")

    async def _load_robots(self) -> None:
        robots_url = f"{urlparse(self._start).scheme}://{self._domain}/robots.txt"
        parser = RobotFileParser()
        try:
            response = await self._http.get(robots_url, headers={"User-Agent": USER_AGENT})
            parser.parse(response.text.splitlines() if response.status_code == 200 else [])
        except httpx.HTTPError:
            parser.parse([])
        self._robots = parser

    def _allowed(self, url: str) -> bool:
        return self._robots is None or self._robots.can_fetch(USER_AGENT, url)

    async def _fetch(self, url: str) -> str | None:
        try:
            response = await self._http.get(
                url, headers={"User-Agent": USER_AGENT}, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            logger.warning("No se pudo descargar", extra={"url": url, "error": str(exc)})
            return None
        if response.status_code != 200 or "html" not in response.headers.get("content-type", ""):
            return None
        return response.text

    def _extract(self, url: str, html: str) -> RawDocument | None:
        text = trafilatura.extract(
            html, url=url, output_format="markdown", include_tables=True, include_comments=False
        )
        if not text or len(text) < 200:
            return None
        metadata = trafilatura.extract_metadata(html, default_url=url)
        title = (metadata.title if metadata and metadata.title else None) or url
        return RawDocument(
            title=title,
            text=text,
            uri=url,
            mime_type="text/html",
            language=(metadata.language if metadata and metadata.language else "es"),
        )

    def _links(self, base: str, html: str) -> list[str]:
        links = []
        for href in LINK.findall(html):
            url, _ = urldefrag(urljoin(base, href))
            parsed = urlparse(url)
            if (
                parsed.scheme in ("http", "https")
                and parsed.netloc == self._domain
                and not parsed.path.lower().endswith(SKIP_EXTENSIONS)
            ):
                links.append(url)
        return links
