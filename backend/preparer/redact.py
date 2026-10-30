"""Redact secrets from install and clone logs before they leave the preparer."""
import re

REDACTED = "[redacted]"

_BEARER = re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._\-+/=]{8,}")
_GHP = re.compile(r"\bghp_[A-Za-z0-9]{20,}")
_GHO = re.compile(r"\bgho_[A-Za-z0-9]{20,}")
_GHU = re.compile(r"\bghu_[A-Za-z0-9]{20,}")
_GHS = re.compile(r"\bghs_[A-Za-z0-9]{20,}")
_GITHUB_PAT = re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")
_AUTH_HEADER = re.compile(
    r"(?i)(AUTHORIZATION:\s*(?:basic|bearer)\s+)(\S+)",
)
_BASIC = re.compile(r"(?i)(://)([^:@/\s]+):([^@/\s]+)(@)")


def redact(text: str | None) -> str:
    if not text:
        return "" if text is None else text
    out = _AUTH_HEADER.sub(r"\1" + REDACTED, text)
    out = _BEARER.sub(r"\1" + REDACTED, out)
    out = _GHP.sub(REDACTED, out)
    out = _GHO.sub(REDACTED, out)
    out = _GHU.sub(REDACTED, out)
    out = _GHS.sub(REDACTED, out)
    out = _GITHUB_PAT.sub(REDACTED, out)
    out = _BASIC.sub(r"\1\2:" + REDACTED + r"\4", out)
    return out
