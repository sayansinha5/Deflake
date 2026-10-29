"""Toloka audit sync. Reviewer answers are not in the run-item payload, so CSV is the fallback."""
import httpx

from app.config import Settings
from app.integrations.escalation.base import ProviderError, ProviderUnavailable

DOCUMENTED_BASE = "https://platform.toloka.ai"


def _base(settings: Settings) -> str:
    raw = (settings.toloka_base_url or DOCUMENTED_BASE).rstrip("/")
    if raw == DOCUMENTED_BASE or raw.startswith(DOCUMENTED_BASE + "/"):
        return raw
    return DOCUMENTED_BASE


class TolokaProvider:
    """Read-only Pipeline API client. It does not start a run."""

    name = "toloka"

    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport

    async def submit_batch(self, items: list[dict]) -> str | None:
        """Launching a run needs a pipeline built in the Toloka app. This does not start one."""
        del items
        if self.settings.toloka_api_key is None:
            raise ProviderUnavailable("Toloka is not configured.")
        if not self.settings.toloka_pipeline_id:
            raise ProviderUnavailable("Toloka pipeline is not configured.")
        raise ProviderUnavailable(
            "Toloka batch launch needs a pipeline designed in the Toloka app."
        )

    async def fetch(self, external_ref: str) -> list[dict]:
        """Item status for one run. The documented payload has no reviewer answers."""
        if not external_ref:
            return []
        body = await self._get(f"/api/v2-beta/runs/{external_ref}/items")
        rows = []
        for item in body.get("items") or []:
            state = item.get("state") or {}
            rows.append({
                "dataset_item_id": item.get("datasetItemId"),
                "status": state.get("status"),
                "answers": [],
            })
        return rows

    async def probe(self) -> dict:
        """Project count, and run count when a pipeline id is configured. No writes."""
        if self.settings.toloka_api_key is None:
            return {"configured": False, "reason": "key_missing"}
        projects = await self._get("/api/v2-beta/projects")
        listed = projects.get("projects") or []
        note = {"configured": True, "projects": len(listed) if isinstance(listed, list) else 0}
        pipeline_id = self.settings.toloka_pipeline_id
        if not pipeline_id:
            note["reason"] = "pipeline_not_configured"
            return note
        try:
            runs = await self._get(f"/api/v2-beta/pipelines/{pipeline_id}/runs")
        except ProviderError as exc:
            note["reason"] = "pipeline_lookup_failed"
            note["detail"] = str(exc)[:120]
            return note
        listed_runs = runs.get("runs") or []
        note["runs"] = len(listed_runs) if isinstance(listed_runs, list) else 0
        if listed_runs:
            note["run_id"] = listed_runs[0].get("id")
        return note

    async def _get(self, path: str) -> dict:
        secret = self.settings.toloka_api_key
        if secret is None:
            raise ProviderUnavailable("Toloka is not configured.")
        headers = {"Authorization": f"ApiKey {secret.get_secret_value()}"}
        async with httpx.AsyncClient(
            base_url=_base(self.settings), headers=headers, transport=self._transport, timeout=30.0,
        ) as client:
            response = await client.get(path)
        if response.status_code >= 400:
            raise ProviderError(f"Toloka HTTP {response.status_code}")
        body = response.json()
        if not isinstance(body, dict):
            raise ProviderError("Toloka response was not an object")
        return body
