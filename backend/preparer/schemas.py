from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

REPO_ID = r"^[a-z0-9][a-z0-9-]{0,63}$"
CLONE_URL = r"^https://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+(?:\.git)?$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PrepareJob(StrictModel):
    repo_id: str = Field(pattern=REPO_ID)
    clone_url: str
    branch: str | None = Field(default=None, max_length=255)
    # Private-repo token. Kept in memory only; never logged or written to disk.
    token: str | None = Field(default=None, max_length=512)
    max_size_mb: int = Field(default=200, ge=1, le=2000)
    clone_timeout_s: int = Field(default=120, ge=10, le=600)
    prepare_timeout_s: int = Field(default=600, ge=30, le=3600)

    @field_validator("clone_url")
    @classmethod
    def _github_https_only(cls, value: str) -> str:
        raw = value.strip().rstrip("/")
        if raw.endswith(".git"):
            raw = raw[:-4]
        if not raw.startswith("https://github.com/"):
            raise ValueError("clone_url must be an https://github.com/{owner}/{repo} URL")
        parts = raw.removeprefix("https://github.com/").split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError("clone_url must be https://github.com/{owner}/{repo}")
        if any(p in (".", "..") for p in parts):
            raise ValueError("clone_url path is invalid")
        return f"https://github.com/{parts[0]}/{parts[1]}.git"


class PrepareResult(StrictModel):
    repo_id: str
    status: Literal["ready", "failed"]
    commit_sha: str | None = None
    default_branch: str | None = None
    test_count: int = 0
    editable_paths: list[str] = Field(default_factory=list)
    error: str | None = None
    requires_python: str | None = None
