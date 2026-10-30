"""GitHub Git Data API helpers for opening a pull request from a verified patch."""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO

import httpx
import structlog
from unidiff import PatchSet, UnidiffParseError

from app.errors import ApiError
from app.services.guardrails import _apply, prepare_diff

log = structlog.get_logger()

API = "https://api.github.com"
UNAUTHORIZED = "GitHub connection expired. Reconnect to continue."


@dataclass(frozen=True)
class RepoPermissions:
    push: bool
    default_branch: str
    full_name: str
    html_url: str


@dataclass(frozen=True)
class CreatedPullRequest:
    number: int
    html_url: str
    branch: str
    head_sha: str


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
    if response.status_code == 422:
        message = "GitHub could not create the pull request."
        try:
            errors = response.json().get("errors") or []
            if errors and isinstance(errors[0], dict) and errors[0].get("message"):
                message = str(errors[0]["message"])
            elif response.json().get("message"):
                message = str(response.json()["message"])
        except Exception:  # noqa: BLE001
            pass
        raise ApiError(422, "github_pr_rejected", message)
    if response.status_code == 403:
        raise ApiError(403, "github_forbidden", "GitHub refused access to this repository.")
    if response.status_code >= 400:
        raise ApiError(502, "github_error", "GitHub returned an unexpected response.")


async def fetch_permissions(token: str, owner: str, name: str) -> RepoPermissions:
    url = f"{API}/repos/{owner}/{name}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=_headers(token))
    except httpx.HTTPError as exc:
        raise ApiError(
            503, "github_unreachable", "GitHub could not be reached. Try again shortly.",
        ) from exc
    if response.status_code != 200:
        _raise_for_status(response)
    data = response.json()
    perms = data.get("permissions") or {}
    return RepoPermissions(
        push=bool(perms.get("push")),
        default_branch=str(data.get("default_branch") or "main"),
        full_name=str(data.get("full_name") or f"{owner}/{name}"),
        html_url=str(data.get("html_url") or f"https://github.com/{owner}/{name}"),
    )


async def fetch_branch_tip(token: str, owner: str, name: str, branch: str) -> str | None:
    url = f"{API}/repos/{owner}/{name}/git/ref/heads/{branch}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=_headers(token))
    except httpx.HTTPError as exc:
        raise ApiError(
            503, "github_unreachable", "GitHub could not be reached. Try again shortly.",
        ) from exc
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        _raise_for_status(response)
    return str((response.json().get("object") or {}).get("sha") or "") or None


async def _get_json(
    client: httpx.AsyncClient, token: str, method: str, url: str, **kwargs,
) -> dict | list:
    response = await client.request(method, url, headers=_headers(token), **kwargs)
    if response.status_code not in {200, 201}:
        _raise_for_status(response)
    return response.json()


async def _file_at_commit(
    client: httpx.AsyncClient, token: str, owner: str, name: str, path: str, ref: str,
) -> str | None:
    """Return UTF-8 text at ref, or None if the file does not exist."""
    url = f"{API}/repos/{owner}/{name}/contents/{path}"
    response = await client.get(url, headers=_headers(token), params={"ref": ref})
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        _raise_for_status(response)
    data = response.json()
    if isinstance(data, list):
        raise ApiError(422, "github_pr_rejected", f"{path} is a directory, not a file.")
    if data.get("encoding") != "base64" or not data.get("content"):
        raise ApiError(422, "github_pr_rejected", f"Could not read {path} from GitHub.")
    raw = base64.b64decode(data["content"])
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(
            422, "github_pr_rejected", f"{path} is not a UTF-8 text file.",
        ) from exc


def branch_name_for(test_id: str, flake_id: str) -> str:
    leaf = (test_id or "test").rsplit("::", 1)[-1]
    leaf = re.sub(r"[^A-Za-z0-9._-]+", "-", leaf).strip("-._")[:40] or "test"
    short = (flake_id or "id")[:8]
    return f"deflake/fix-{leaf}-{short}"


def short_test_label(test_id: str) -> str:
    return (test_id or "test").rsplit("::", 1)[-1]


async def create_pull_request_from_diff(
    token: str,
    *,
    owner: str,
    name: str,
    base_commit_sha: str,
    default_branch: str,
    branch: str,
    title: str,
    body: str,
    diff: str,
) -> CreatedPullRequest:
    """
    Apply a unified diff onto base_commit_sha via the Git Data API, push a branch,
    and open a PR targeting default_branch.
    """
    prepared = prepare_diff(diff)
    try:
        patchset = PatchSet(StringIO(prepared))
    except UnidiffParseError as exc:
        raise ApiError(422, "invalid_patch", "The verified patch could not be parsed.") from exc
    if not list(patchset):
        raise ApiError(422, "invalid_patch", "The verified patch has no file changes.")

    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            commit = await _get_json(
                client, token, "GET",
                f"{API}/repos/{owner}/{name}/git/commits/{base_commit_sha}",
            )
            base_tree = str((commit.get("tree") or {}).get("sha") or "")
            if not base_tree:
                raise ApiError(502, "github_error", "GitHub returned an unexpected response.")

            tree_items: list[dict] = []
            for patched in patchset:
                path = patched.path
                if patched.is_removed_file:
                    tree_items.append({
                        "path": path, "mode": "100644", "type": "blob", "sha": None,
                    })
                    continue
                original = await _file_at_commit(
                    client, token, owner, name, path, base_commit_sha,
                )
                if patched.is_added_file:
                    original = original or ""
                elif original is None:
                    raise ApiError(
                        422,
                        "github_pr_rejected",
                        f"{path} was not found at the scanned commit.",
                    )
                try:
                    updated = _apply(original, patched)
                except ValueError as exc:
                    raise ApiError(
                        422,
                        "github_pr_rejected",
                        f"The patch no longer applies cleanly to {path}.",
                    ) from exc
                blob = await _get_json(
                    client, token, "POST",
                    f"{API}/repos/{owner}/{name}/git/blobs",
                    json={"content": updated, "encoding": "utf-8"},
                )
                tree_items.append({
                    "path": path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob["sha"],
                })

            tree = await _get_json(
                client, token, "POST",
                f"{API}/repos/{owner}/{name}/git/trees",
                json={"base_tree": base_tree, "tree": tree_items},
            )
            new_commit = await _get_json(
                client, token, "POST",
                f"{API}/repos/{owner}/{name}/git/commits",
                json={
                    "message": title,
                    "tree": tree["sha"],
                    "parents": [base_commit_sha],
                },
            )
            head_sha = str(new_commit["sha"])
            await _get_json(
                client, token, "POST",
                f"{API}/repos/{owner}/{name}/git/refs",
                json={"ref": f"refs/heads/{branch}", "sha": head_sha},
            )
            pr = await _get_json(
                client, token, "POST",
                f"{API}/repos/{owner}/{name}/pulls",
                json={
                    "title": title,
                    "head": branch,
                    "base": default_branch,
                    "body": body,
                },
            )
    except httpx.HTTPError as exc:
        log.warning("github_pr_unreachable")
        raise ApiError(
            503, "github_unreachable", "GitHub could not be reached. Try again shortly.",
        ) from exc

    return CreatedPullRequest(
        number=int(pr["number"]),
        html_url=str(pr["html_url"]),
        branch=branch,
        head_sha=head_sha,
    )
