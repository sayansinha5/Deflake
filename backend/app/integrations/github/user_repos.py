"""Authenticated GitHub repo listing and metadata for a connected user."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import structlog

from app.errors import ApiError

log = structlog.get_logger()

GITHUB_API = "https://api.github.com"
PER_PAGE = 50
UNAUTHORIZED = "GitHub connection expired. Reconnect to continue."


@dataclass(frozen=True)
class UserRepoItem:
    owner: str
    name: str
    full_name: str
    html_url: str
    description: str
    private: bool
    language: str | None
    updated_at: str | None
    default_branch: str
    size_kb: int


@dataclass(frozen=True)
class AuthedRepoMeta:
    owner: str
    name: str
    full_name: str
    html_url: str
    description: str
    default_branch: str
    size_kb: int
    is_private: bool


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Deflake",
        "Authorization": f"Bearer {token}",
    }


def _rate_limit_message(response: httpx.Response) -> str:
    reset = response.headers.get("x-ratelimit-reset")
    if reset and reset.isdigit():
        when = datetime.fromtimestamp(int(reset), tz=UTC)
        return (
            "GitHub rate limit reached. Try again after "
            f"{when.strftime('%Y-%m-%d %H:%M:%S')} UTC."
        )
    return "GitHub rate limit reached. Try again later."


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code == 401:
        raise ApiError(401, "github_unauthorized", UNAUTHORIZED)
    if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
        raise ApiError(429, "github_rate_limited", _rate_limit_message(response))
    if response.status_code == 404:
        raise ApiError(404, "repo_not_found", "Repository not found on GitHub.")
    if response.status_code == 403:
        raise ApiError(403, "github_forbidden", "GitHub refused access to this repository.")
    if response.status_code >= 400:
        raise ApiError(502, "github_error", "GitHub returned an unexpected response.")


def _item_from_payload(data: dict) -> UserRepoItem:
    owner = str((data.get("owner") or {}).get("login") or "")
    name = str(data.get("name") or "")
    return UserRepoItem(
        owner=owner,
        name=name,
        full_name=str(data.get("full_name") or f"{owner}/{name}"),
        html_url=str(data.get("html_url") or f"https://github.com/{owner}/{name}"),
        description=str(data.get("description") or ""),
        private=bool(data.get("private")),
        language=data.get("language"),
        updated_at=data.get("updated_at"),
        default_branch=str(data.get("default_branch") or "main"),
        size_kb=int(data.get("size") or 0),
    )


def _matches(item: UserRepoItem, *, q: str | None, python_only: bool) -> bool:
    if python_only and (item.language or "").lower() != "python":
        return False
    if q:
        needle = q.lower().strip()
        if needle and needle not in item.full_name.lower() and needle not in item.name.lower():
            return False
    return True


async def list_accessible_repos(
    token: str,
    *,
    page: int = 1,
    q: str | None = None,
    python_only: bool = True,
) -> tuple[list[UserRepoItem], bool]:
    """
    List repos the token can access, newest first.

    When filters are on, walk a few GitHub pages to fill up to PER_PAGE matches.
    """
    page = max(1, page)
    q = (q or "").strip() or None
    matched: list[UserRepoItem] = []
    # Map UI page → start offset in the filtered stream by scanning earlier pages.
    skip = (page - 1) * PER_PAGE
    seen = 0
    github_page = 1
    has_more_github = True
    # Cap API fan-out so a sparse filter cannot hammer GitHub.
    max_github_pages = 8

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            while has_more_github and github_page <= max_github_pages and len(matched) < PER_PAGE:
                response = await client.get(
                    f"{GITHUB_API}/user/repos",
                    headers=_headers(token),
                    params={
                        "sort": "updated",
                        "direction": "desc",
                        "per_page": PER_PAGE,
                        "page": github_page,
                        "affiliation": "owner,collaborator,organization_member",
                    },
                )
                if response.status_code != 200:
                    _raise_for_status(response)
                batch = response.json()
                if not isinstance(batch, list):
                    raise ApiError(502, "github_error", "GitHub returned an unexpected response.")
                if len(batch) < PER_PAGE:
                    has_more_github = False
                for raw in batch:
                    item = _item_from_payload(raw)
                    if not _matches(item, q=q, python_only=python_only):
                        continue
                    if seen < skip:
                        seen += 1
                        continue
                    matched.append(item)
                    if len(matched) >= PER_PAGE:
                        break
                github_page += 1
    except httpx.HTTPError as exc:
        log.warning("github_list_unreachable")
        raise ApiError(
            503, "github_unreachable", "GitHub could not be reached. Try again shortly.",
        ) from exc

    has_more = len(matched) >= PER_PAGE
    return matched[:PER_PAGE], has_more


async def fetch_repo_with_token(
    token: str, owner: str, name: str, *, max_size_mb: int,
) -> AuthedRepoMeta:
    url = f"{GITHUB_API}/repos/{owner}/{name}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=_headers(token))
    except httpx.HTTPError as exc:
        log.warning("github_meta_unreachable")
        raise ApiError(
            503, "github_unreachable", "GitHub could not be reached. Try again shortly.",
        ) from exc

    if response.status_code != 200:
        _raise_for_status(response)

    data = response.json()
    size_kb = int(data.get("size") or 0)
    if size_kb > max_size_mb * 1024:
        raise ApiError(
            422,
            "repo_too_large",
            f"Repository is over the limit of {max_size_mb} MB.",
        )
    owner_login = str((data.get("owner") or {}).get("login") or owner)
    repo_name = str(data.get("name") or name)
    return AuthedRepoMeta(
        owner=owner_login,
        name=repo_name,
        full_name=str(data.get("full_name") or f"{owner_login}/{repo_name}"),
        html_url=str(data.get("html_url") or f"https://github.com/{owner_login}/{repo_name}"),
        description=str(data.get("description") or ""),
        default_branch=str(data.get("default_branch") or "main"),
        size_kb=size_kb,
        is_private=bool(data.get("private")),
    )
