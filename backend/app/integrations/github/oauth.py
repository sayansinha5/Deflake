"""GitHub OAuth App helpers: PKCE, authorize URL, token exchange, revoke."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from threading import Lock
from urllib.parse import urlencode

import httpx
import structlog

from app.config import Settings
from app.errors import ApiError

log = structlog.get_logger()

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API = "https://api.github.com"
STATE_TTL_S = 10 * 60


@dataclass
class OAuthPending:
    user_id: str
    jti: str
    code_verifier: str
    expires_at: float


_pending: dict[str, OAuthPending] = {}
_lock = Lock()


def clear_oauth_states() -> None:
    with _lock:
        _pending.clear()


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def create_oauth_state(user_id: str, jti: str) -> tuple[str, str]:
    """Return (state, code_challenge). Stores verifier server-side."""
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()
    with _lock:
        _pending[state] = OAuthPending(
            user_id=user_id,
            jti=jti,
            code_verifier=verifier,
            expires_at=time.monotonic() + STATE_TTL_S,
        )
    return state, challenge


def consume_oauth_state(state: str | None) -> OAuthPending:
    if not state:
        raise ApiError(400, "oauth_state_invalid", "GitHub connection could not be completed.")
    with _lock:
        # Drop expired entries opportunistically.
        now = time.monotonic()
        for key in [k for k, v in _pending.items() if v.expires_at <= now]:
            _pending.pop(key, None)
        pending = _pending.pop(state, None)
    if pending is None:
        raise ApiError(400, "oauth_state_invalid", "GitHub connection could not be completed.")
    if pending.expires_at <= time.monotonic():
        raise ApiError(400, "oauth_state_invalid", "GitHub connection could not be completed.")
    return pending


def authorize_url(settings: Settings, state: str, code_challenge: str) -> str:
    params = {
        "client_id": settings.github_oauth_client_id,
        "redirect_uri": settings.github_oauth_redirect_uri,
        "scope": settings.github_oauth_scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(settings: Settings, code: str, code_verifier: str) -> tuple[str, str]:
    """Exchange the authorization code. Returns (access_token, scope_string)."""
    data = {
        "client_id": settings.github_oauth_client_id,
        "client_secret": settings.github_oauth_client_secret.get_secret_value(),
        "code": code,
        "redirect_uri": settings.github_oauth_redirect_uri,
        "code_verifier": code_verifier,
    }
    headers = {"Accept": "application/json", "User-Agent": "Deflake"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(TOKEN_URL, data=data, headers=headers)
    except httpx.HTTPError as exc:
        log.warning("github_oauth_exchange_unreachable")
        raise ApiError(
            503, "github_unreachable", "GitHub could not be reached. Try again shortly.",
        ) from exc
    if response.status_code != 200:
        raise ApiError(502, "github_oauth_failed", "GitHub refused the connection.")
    body = response.json()
    token = body.get("access_token")
    if not token or not isinstance(token, str):
        raise ApiError(502, "github_oauth_failed", "GitHub refused the connection.")
    scope = str(body.get("scope") or settings.github_oauth_scopes)
    return token, scope


async def fetch_github_user(access_token: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Deflake",
        "Authorization": f"Bearer {access_token}",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(f"{API}/user", headers=headers)
    except httpx.HTTPError as exc:
        raise ApiError(
            503, "github_unreachable", "GitHub could not be reached. Try again shortly.",
        ) from exc
    if response.status_code == 401:
        raise ApiError(401, "github_unauthorized", "GitHub connection expired. Reconnect to continue.")
    if response.status_code != 200:
        raise ApiError(502, "github_error", "GitHub returned an unexpected response.")
    return response.json()


async def revoke_token(settings: Settings, access_token: str) -> None:
    """Best-effort revoke. Never logs the token."""
    client_id = settings.github_oauth_client_id
    secret = settings.github_oauth_client_secret
    if not client_id or secret is None:
        return
    auth = (client_id, secret.get_secret_value())
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Deflake",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.delete(
                f"{API}/applications/{client_id}/token",
                headers=headers,
                auth=auth,
                json={"access_token": access_token},
            )
    except httpx.HTTPError:
        log.warning("github_revoke_unreachable")


def success_redirect(settings: Settings, status: str) -> str:
    """Fixed success URL only — never redirect to a request-supplied URL."""
    base = settings.github_oauth_success_url.split("?", 1)[0]
    sep = "&" if "?" in settings.github_oauth_success_url else "?"
    # Prefer the configured URL's existing query, then append github=.
    if "?" in settings.github_oauth_success_url:
        return f"{settings.github_oauth_success_url}&github={status}"
    return f"{base}{sep}github={status}"


def constant_time_state_match(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())
