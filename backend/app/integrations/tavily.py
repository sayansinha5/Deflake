"""Tavily search with a 24-hour cache. Queries must already be path-free."""
import hashlib
from datetime import timedelta
from typing import Protocol

import structlog
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db.models import SearchCache, utcnow
from app.security.redact import redact

log = structlog.get_logger()

CACHE_TTL = timedelta(hours=24)
TIMEOUT_S = 15


class SearchUnavailable(RuntimeError):
    pass


class SearchClient(Protocol):
    async def search(self, query: str) -> list[dict]: ...


class TavilySearch:
    """Uses tavily-python's AsyncTavilyClient. No key means search is unavailable."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def search(self, query: str) -> list[dict]:
        key = self.settings.tavily_api_key
        if not self.settings.tavily_enabled or key is None:
            raise SearchUnavailable("Tavily is disabled")
        from tavily import AsyncTavilyClient

        client = AsyncTavilyClient(api_key=key.get_secret_value())
        depth = self.settings.tavily_search_depth
        payload = await client.search(
            query=query,
            search_depth=depth,
            max_results=self.settings.tavily_max_results,
            timeout=TIMEOUT_S,
            include_answer=False,
            include_raw_content=False,
        )
        rows = []
        for item in (payload or {}).get("results") or []:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            rows.append({
                "title": redact(str(item.get("title") or ""))[:300],
                "url": url[:2048],
                "content": redact(str(item.get("content") or ""))[:300],
                "score": item.get("score"),
            })
        return rows[: self.settings.tavily_max_results]


def _hash(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


async def cached_search(sessionmaker, client: SearchClient, query: str) -> tuple[list[dict], bool]:
    """Returns (results, from_cache). Failures are not cached."""
    digest = _hash(query)
    async with sessionmaker() as session:
        row = await session.get(SearchCache, digest)
        if row is not None and row.fetched_at >= utcnow() - CACHE_TTL:
            return list(row.results or []), True
    results = await client.search(query)
    async with sessionmaker() as session:
        existing = await session.get(SearchCache, digest)
        if existing is None:
            session.add(SearchCache(
                query_hash=digest, query=query[:200], results=results, fetched_at=utcnow(),
            ))
        else:
            existing.query = query[:200]
            existing.results = results
            existing.fetched_at = utcnow()
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
    return results, False
