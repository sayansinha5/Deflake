import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.config import Settings

COOKIE_NAME = "deflake_session"
COOKIE_PATH = "/api"
ALGORITHM = "HS256"


@dataclass(frozen=True)
class SessionClaims:
    user_id: str
    jti: str
    is_admin: bool
    issued_at: datetime
    expires_at: datetime


class SessionExpired(Exception):
    pass


class SessionInvalid(Exception):
    pass


def issue_token(settings: Settings, user_id: str, is_admin: bool) -> tuple[str, SessionClaims]:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.jwt_ttl_minutes)
    claims = SessionClaims(
        user_id=user_id, jti=str(uuid.uuid4()), is_admin=is_admin,
        issued_at=now, expires_at=expires,
    )
    token = jwt.encode(
        {"sub": user_id, "jti": claims.jti, "is_admin": is_admin,
         "iat": now.timestamp(), "exp": expires.timestamp()},
        settings.jwt_secret.get_secret_value(),
        algorithm=ALGORITHM,
    )
    return token, claims


def decode_token(settings: Settings, token: str) -> SessionClaims:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret.get_secret_value(), algorithms=[ALGORITHM],
            options={"require": ["sub", "jti", "iat", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise SessionExpired from exc
    except jwt.PyJWTError as exc:
        raise SessionInvalid from exc
    return SessionClaims(
        user_id=payload["sub"],
        jti=payload["jti"],
        is_admin=bool(payload.get("is_admin")),
        issued_at=datetime.fromtimestamp(payload["iat"], UTC),
        expires_at=datetime.fromtimestamp(payload["exp"], UTC),
    )


def cookie_kwargs(settings: Settings) -> dict:
    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": "strict",
        "path": COOKIE_PATH,
    }


def salted_hash(settings: Settings, value: str | None) -> str | None:
    if value is None:
        return None
    salt = settings.jwt_secret.get_secret_value().encode()
    return hashlib.sha256(salt + value.encode()).hexdigest()
