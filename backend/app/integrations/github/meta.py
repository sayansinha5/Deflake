"""Public repository metadata via the GitHub REST API. The API owns these calls."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import structlog

from app.config import Settings
from app.errors import ApiError

log = structlog.get_logger()

GITHUB_API = "https://api.github.com"
NOT_PUBLIC = (
    "Repository not found or not public. Connect GitHub to import private repositories."
)


@dataclass(frozen=True)
class PublicRepoMeta:
    owner: str
    name: str
    full_name: str
    html_url: str
    description: str
    default_branch: str
    size_kb: int
    is_private: bool


def _auth_headers(settings: Settings) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Deflake",
    }
    token = settings.github_public_token
    if token is not None:
        headers["Authorization"] = f"Bearer {token.get_secret_value()}"
    return headers


def _rate_limit_message(response: httpx.Response) -> str:
    reset = response.headers.get("x-ratelimit-reset")
    if reset and reset.isdigit():
        when = datetime.fromtimestamp(int(reset), tz=UTC)
        return (
            "GitHub rate limit reached. Try again after "
            f"{when.strftime('%Y-%m-%d %H:%M:%S')} UTC."
        )
    return "GitHub rate limit reached. Try again later."


async def fetch_public_repo(
    settings: Settings, owner: str, name: str, *, max_size_mb: int,
) -> PublicRepoMeta:
    """
    One metadata call. Repo must exist, be public, and be under max_size_mb.
    Does not retry on rate limits.
    """
    url = f"{GITHUB_API}/repos/{owner}/{name}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=_auth_headers(settings))
    except httpx.HTTPError as exc:
        log.warning("github_meta_unreachable", error=str(exc))
        raise ApiError(
            503, "github_unreachable", "GitHub could not be reached. Try again shortly.",
        ) from exc

    if response.status_code == 404:
        raise ApiError(404, "repo_not_public", NOT_PUBLIC)
    if response.status_code == 401:
        raise ApiError(404, "repo_not_public", NOT_PUBLIC)
    if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
        raise ApiError(429, "github_rate_limited", _rate_limit_message(response))
    if response.status_code == 403:
        # Private repo often looks like 404 for unauthenticated; treat other 403s carefully.
        raise ApiError(404, "repo_not_public", NOT_PUBLIC)
    if response.status_code != 200:
        raise ApiError(502, "github_error", "GitHub returned an unexpected response.")

    data = response.json()
    if data.get("private") is True:
        raise ApiError(404, "repo_not_public", NOT_PUBLIC)

    size_kb = int(data.get("size") or 0)
    if size_kb > max_size_mb * 1024:
        raise ApiError(
            422,
            "repo_too_large",
            f"Repository is over the limit of {max_size_mb} MB.",
        )

    return PublicRepoMeta(
        owner=str(data.get("owner", {}).get("login") or owner),
        name=str(data.get("name") or name),
        full_name=str(data.get("full_name") or f"{owner}/{name}"),
        html_url=str(data.get("html_url") or f"https://github.com/{owner}/{name}"),
        description=str(data.get("description") or ""),
        default_branch=str(data.get("default_branch") or "main"),
        size_kb=size_kb,
        is_private=False,
    )
