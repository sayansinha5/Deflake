from typing import Any

import httpx
import structlog

from app.config import Settings
from app.errors import ApiError

log = structlog.get_logger()


class PreparerClient:
    def __init__(self, settings: Settings) -> None:
        self._url = settings.preparer_url.rstrip("/")
        self._headers = {
            "X-Preparer-Secret": settings.preparer_shared_secret.get_secret_value(),
        }
        self._timeout = httpx.Timeout(
            connect=5.0,
            read=float(settings.prepare_timeout_s + 30),
            write=30.0,
            pool=10.0,
        )

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{self._url}/healthz")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def prepare(self, job: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._url}/prepare", json=job, headers=self._headers,
                )
        except httpx.HTTPError as exc:
            log.warning("preparer_unreachable", error=str(exc))
            raise ApiError(
                503, "preparer_unreachable", "The repository preparer is not reachable.",
            ) from exc
        if response.status_code == 401:
            raise ApiError(
                503, "preparer_unauthorised", "The repository preparer refused the request.",
            )
        if response.status_code == 422:
            body = response.json()
            return body if isinstance(body, dict) else {"status": "failed", "error": str(body)}
        if response.status_code != 200:
            raise ApiError(
                502, "preparer_error",
                "The repository preparer returned an unexpected response.",
            )
        return response.json()

    async def cleanup(self, repo_id: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(
                    f"{self._url}/repos/{repo_id}", headers=self._headers,
                )
        except httpx.HTTPError as exc:
            log.warning("preparer_cleanup_unreachable", error=str(exc), repo_id=repo_id)
            raise ApiError(
                503, "preparer_unreachable", "The repository preparer is not reachable.",
            ) from exc
        if response.status_code == 401:
            raise ApiError(
                503, "preparer_unauthorised", "The repository preparer refused the request.",
            )
        if response.status_code not in {200, 404}:
            raise ApiError(
                502, "preparer_error",
                "The repository preparer returned an unexpected response.",
            )
