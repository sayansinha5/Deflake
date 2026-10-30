"""Fernet helpers for GitHub OAuth access tokens. Decrypt only in API memory."""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings
from app.errors import ApiError


def _fernet(settings: Settings) -> Fernet:
    key = settings.github_token_encryption_key
    if key is None:
        raise ApiError(
            503,
            "oauth_misconfigured",
            "GitHub token encryption is not configured.",
        )
    try:
        return Fernet(key.get_secret_value().encode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ApiError(
            503,
            "oauth_misconfigured",
            "GitHub token encryption is not configured.",
        ) from exc


def encrypt_token(settings: Settings, token: str) -> str:
    return _fernet(settings).encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(settings: Settings, blob: str) -> str:
    try:
        return _fernet(settings).decrypt(blob.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ApiError(
            503,
            "oauth_token_corrupt",
            "The stored GitHub connection could not be read. Reconnect GitHub.",
        ) from exc
