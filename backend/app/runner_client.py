from typing import Any

import httpx
import structlog

from app.config import Settings
from app.errors import ApiError

log = structlog.get_logger()


class RunnerClient:
    def __init__(self, settings: Settings) -> None:
        self._url = settings.runner_url.rstrip("/")
        self._headers = {"X-Runner-Secret": settings.runner_shared_secret.get_secret_value()}
        self._timeout = httpx.Timeout(connect=5.0, read=900.0, write=30.0, pool=10.0)

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self._url}/healthz")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def submit(self, job: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(f"{self._url}/jobs", json=job, headers=self._headers)
        except httpx.HTTPError as exc:
            log.warning("runner_unreachable", error=str(exc))
            raise ApiError(503, "runner_unreachable", "The test runner is not reachable.") from exc
        if r.status_code == 401:
            raise ApiError(503, "runner_unauthorised", "The test runner refused the request.")
        if r.status_code == 422:
            body = r.json()
            detail = body.get("error") or body
            raise ApiError(
                422, detail.get("code", "runner_rejected"),
                detail.get("message", "The test runner rejected the job."),
            )
        if r.status_code != 200:
            raise ApiError(502, "runner_error", "The test runner returned an unexpected response.")
        return r.json()
