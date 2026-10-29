"""GitHub issue escalation. REST shape is the documented Issues API."""
import re

import httpx

from app.config import Settings
from app.integrations.escalation.base import (
    ProviderError,
    ProviderUnavailable,
    StatusResult,
    SubmitResult,
)

API = "https://api.github.com"
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubIssueProvider:
    name = "github_issue"

    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport

    async def submit(self, bundle: dict, idempotency_key: str) -> SubmitResult:
        repo = self._repo()
        title = f"{bundle.get('app') or 'Deflake'}: {bundle.get('test_id') or 'flaky test'}"[:200]
        body = str(bundle.get("text") or "Evidence bundle.")[:20000]
        # Documented: POST /repos/{owner}/{repo}/issues
        data = await self._request("POST", f"/repos/{repo}/issues", {"title": title, "body": body})
        number = data.get("number")
        if not isinstance(number, int):
            raise ProviderError("GitHub issue response had no number")
        return SubmitResult(provider=self.name, external_ref=str(number), status="submitted")

    async def status(self, external_ref: str) -> StatusResult:
        if not external_ref.isdigit():
            raise ProviderError("GitHub external_ref is not an issue number")
        repo = self._repo()
        data = await self._request("GET", f"/repos/{repo}/issues/{external_ref}")
        if data.get("state") == "closed":
            return StatusResult(status="resolved", response="GitHub issue closed.")
        return StatusResult(status="submitted", response=None)

    def _repo(self) -> str:
        repo = self.settings.github_repo or ""
        if self.settings.github_token is None or not _REPO.fullmatch(repo):
            raise ProviderUnavailable("GitHub issues are not configured.")
        return repo

    async def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        token = self.settings.github_token
        if token is None:
            raise ProviderUnavailable("GitHub issues are not configured.")
        headers = {
            "Authorization": f"Bearer {token.get_secret_value()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "deflake",
        }
        async with httpx.AsyncClient(transport=self._transport, timeout=30.0) as client:
            response = await client.request(method, f"{API}{path}", headers=headers, json=payload)
        if response.status_code >= 400:
            raise ProviderError(f"GitHub HTTP {response.status_code}")
        data = response.json()
        if not isinstance(data, dict):
            raise ProviderError("GitHub response was not an object")
        return data
