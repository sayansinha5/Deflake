"""Redact secrets and identifiers before text leaves the process or is stored."""
import re

REDACTED = "[redacted]"
REDACTED_EMAIL = "[redacted-email]"
REDACTED_PATH = "~"

_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
_BEARER = re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._\-+/=]{8,}")
_SK = re.compile(r"\bsk-[A-Za-z0-9]{10,}")
_GHP = re.compile(r"\bghp_[A-Za-z0-9]{20,}")
_GHO = re.compile(r"\bgho_[A-Za-z0-9]{20,}")
_GHU = re.compile(r"\bghu_[A-Za-z0-9]{20,}")
_GHS = re.compile(r"\bghs_[A-Za-z0-9]{20,}")
_GITHUB_PAT = re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")
_AKIA = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_KEY_VALUE = re.compile(
    r"(?i)(\b(?:api[_-]?key|secret|token|password|passwd|authorization)\b\s*[:=]\s*)"
    r"([^\s'\"#]{12,})"
)
_HOME_UNIX = re.compile(r"(?i)(?<![A-Za-z0-9_])/(?:home|Users)/[^\s/]+")
_HOME_WIN = re.compile(r"(?i)[A-Z]:\\Users\\[^\s\\]+")
_GENERIC_TOKEN = re.compile(
    r"(?i)(\b(?:api[_-]?key|secret|token)\b[^A-Za-z0-9]{0,8})([A-Za-z0-9_\-+/=]{24,})"
)


def redact(text: str | None) -> str:
    if not text:
        return "" if text is None else text
    out = _PRIVATE_KEY.sub(REDACTED, text)
    out = _JWT.sub(REDACTED, out)
    out = _BEARER.sub(r"\1" + REDACTED, out)
    out = _SK.sub(REDACTED, out)
    out = _GHP.sub(REDACTED, out)
    out = _GHO.sub(REDACTED, out)
    out = _GHU.sub(REDACTED, out)
    out = _GHS.sub(REDACTED, out)
    out = _GITHUB_PAT.sub(REDACTED, out)
    out = _AKIA.sub(REDACTED, out)
    out = _KEY_VALUE.sub(r"\1" + REDACTED, out)
    out = _GENERIC_TOKEN.sub(r"\1" + REDACTED, out)
    out = _EMAIL.sub(REDACTED_EMAIL, out)
    out = _HOME_WIN.sub(REDACTED_PATH, out)
    out = _HOME_UNIX.sub(REDACTED_PATH, out)
    return out


def redact_obj(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_obj(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_obj(v) for v in value]
    return value
