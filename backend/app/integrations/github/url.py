"""Parse the only GitHub URL shape Deflake accepts from users."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# Owner: 1–39 letters, digits or single hyphens; not starting or ending with a hyphen.
_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
# Repo: 1–100 letters, digits, `.`, `_`, `-`; not `.` or `..`.
_REPO = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class GitHubUrlError(ValueError):
    """Raised when a user-supplied URL is not an allowed GitHub repository URL."""


@dataclass(frozen=True)
class ParsedGitHubRepo:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def html_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}"

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}.git"


def parse_github_repo_url(raw: str) -> ParsedGitHubRepo:
    """
    Accept only https://github.com/{owner}/{repo}, optionally ending in .git or /.

    Never fetch the caller's string: parse owner/repo and rebuild URLs server-side.
    """
    if raw is None or not isinstance(raw, str):
        raise GitHubUrlError("Enter a GitHub repository URL.")
    text = raw.strip()
    if not text or any(ch.isspace() for ch in text):
        raise GitHubUrlError("Enter a GitHub repository URL.")

    parsed = urlparse(text)
    if parsed.scheme.lower() != "https":
        raise GitHubUrlError("Use an https://github.com/{owner}/{repo} URL.")
    if parsed.username is not None or parsed.password is not None:
        raise GitHubUrlError("The repository URL must not include a username or password.")
    if parsed.port is not None:
        raise GitHubUrlError("The repository URL must not include a port.")
    if parsed.query:
        raise GitHubUrlError("The repository URL must not include a query string.")
    if parsed.fragment:
        raise GitHubUrlError("The repository URL must not include a fragment.")
    if (parsed.hostname or "").lower() != "github.com":
        raise GitHubUrlError("Only github.com repository URLs are supported.")

    path = (parsed.path or "").strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    path = path.strip("/")
    parts = [p for p in path.split("/") if p]
    if len(parts) != 2:
        raise GitHubUrlError("Use an https://github.com/{owner}/{repo} URL.")

    owner, name = parts[0], parts[1]
    return validate_owner_repo(owner, name)


def validate_owner_repo(owner: str, name: str) -> ParsedGitHubRepo:
    """Validate owner/name the same way as a parsed URL (picker import)."""
    if not isinstance(owner, str) or not isinstance(name, str):
        raise GitHubUrlError("Choose a GitHub repository.")
    owner = owner.strip()
    name = name.strip()
    if not _OWNER.fullmatch(owner):
        raise GitHubUrlError("The repository owner is invalid.")
    if name in {".", ".."} or not _REPO.fullmatch(name):
        raise GitHubUrlError("The repository name is invalid.")
    return ParsedGitHubRepo(owner=owner, name=name)
