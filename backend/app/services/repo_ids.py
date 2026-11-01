"""Stable slug ids for imported GitHub repositories."""
from __future__ import annotations

import hashlib
import re

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def imported_repo_id(owner: str, name: str) -> str:
    """
    Build a repos.id slug from owner/name.

    Prefer a readable owner-name form when it fits the existing slug pattern;
    otherwise fall back to a short hash so the id stays unique and valid.
    """
    base = f"{owner}-{name}".lower()
    base = re.sub(r"[^a-z0-9-]+", "-", base)
    base = re.sub(r"-{2,}", "-", base).strip("-")
    if base and base[0].isdigit():
        base = f"r-{base}"
    if base and _SLUG.fullmatch(base):
        return base
    digest = hashlib.sha256(f"{owner}/{name}".lower().encode("utf-8")).hexdigest()[:20]
    return f"gh-{digest}"


def imported_repo_id_for_user(owner: str, name: str, user_id: str) -> str:
    """Per-user slug so two accounts can import the same GitHub repo independently."""
    short = user_id.replace("-", "")[:8]
    return imported_repo_id(f"{owner}-u{short}", name)


def demo_repo_id_for_user(template_id: str, user_id: str) -> str:
    """Per-user demo slug; filesystem still uses the template path (e.g. flaky-shop)."""
    short = user_id.replace("-", "")[:8]
    base = f"{template_id}-u{short}".lower()
    base = re.sub(r"[^a-z0-9-]+", "-", base)
    base = re.sub(r"-{2,}", "-", base).strip("-")
    if base and _SLUG.fullmatch(base):
        return base
    digest = hashlib.sha256(f"{template_id}:{user_id}".encode("utf-8")).hexdigest()[:20]
    return f"demo-{digest}"
