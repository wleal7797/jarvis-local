"""Descarga artículos de Wikipedia (texto plano) con su API pública.

Se eligió la API por temas en lugar del volcado completo (~5 GB comprimido, ~8 millones
de fragmentos): en este equipo vectorizar toda la Wikipedia tardaría más de un mes.
Licencia del contenido: CC BY-SA 4.0 (se guarda en la fuente).
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx

from app.services.ingestion.base import USER_AGENT, LoaderError, RawDocument

logger = logging.getLogger(__name__)

LICENSE = "CC BY-SA 4.0"
# Secciones que no aportan conocimiento útil para responder.
SKIPPED_SECTIONS = {
    "referencias",
    "notas",
    "enlaces externos",
    "bibliografía",
    "véase también",
    "fuentes",
    "notas y referencias",
    "lecturas adicionales",
}
WIKI_HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$")
MAX_CATEGORY_PAGES = 500


def wiki_to_markdown(title: str, text: str) -> str:
    """Convierte los títulos '== Historia ==' en '## Historia' y quita secciones de relleno."""
    lines = [f"# {title}"]
    skipping = False
    skip_level = 0
    for line in text.splitlines():
        match = WIKI_HEADING.match(line)
        if match:
            level = len(match.group(1))
            name = match.group(2).strip()
            if skipping and level > skip_level:
                continue
            skipping = name.lower() in SKIPPED_SECTIONS
            skip_level = level
            if not skipping:
                lines.append(f"{'#' * min(level, 3)} {name}")
            continue
        if not skipping:
            lines.append(line)
    return "\n".join(lines).strip()


class WikipediaLoader:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        titles: list[str] | None = None,
        category: str | None = None,
        limit: int = 50,
        language: str = "es",
        delay_seconds: float = 0.5,
    ) -> None:
        if not titles and not category:
            raise LoaderError("Indica títulos de artículos o una categoría")
        self._http = http
        self._titles = [t.strip() for t in (titles or []) if t.strip()]
        self._category = category
        self._limit = max(1, min(limit, MAX_CATEGORY_PAGES))
        self._language = language
        self._api = f"https://{language}.wikipedia.org/w/api.php"
        self._delay = delay_seconds

    async def load(self) -> AsyncIterator[RawDocument]:
        titles = list(self._titles)
        if self._category:
            titles += await self._category_members(self._category)
        loaded = 0
        for title in dict.fromkeys(titles):  # sin repetidos, en orden
            document = await self._article(title)
            if document is not None:
                loaded += 1
                yield document
            await asyncio.sleep(self._delay)
        if loaded == 0:
            raise LoaderError("No se encontró ningún artículo")

    async def _get(self, params: dict) -> dict:
        try:
            response = await self._http.get(
                self._api,
                params={"format": "json", "formatversion": "2", **params},
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LoaderError(f"Wikipedia no respondió: {exc}") from exc
        return response.json()

    async def _category_members(self, category: str) -> list[str]:
        name = category if ":" in category else f"Categoría:{category}"
        data = await self._get(
            {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": name,
                "cmtype": "page",
                "cmlimit": str(self._limit),
            }
        )
        return [m["title"] for m in data.get("query", {}).get("categorymembers", [])]

    async def _article(self, title: str) -> RawDocument | None:
        data = await self._get(
            {
                "action": "query",
                "prop": "extracts",
                "explaintext": "1",
                "exsectionformat": "wiki",
                "redirects": "1",
                "titles": title,
            }
        )
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing") or not pages[0].get("extract"):
            logger.info("Artículo no encontrado", extra={"title": title})
            return None
        page = pages[0]
        real_title = page["title"]
        slug = quote(real_title.replace(" ", "_"))
        return RawDocument(
            title=real_title,
            text=wiki_to_markdown(real_title, page["extract"]),
            uri=f"https://{self._language}.wikipedia.org/wiki/{slug}",
            language=self._language,
            metadata={"license": LICENSE, "pageid": page.get("pageid")},
        )
