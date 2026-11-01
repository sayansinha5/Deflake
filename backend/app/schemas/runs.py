from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

REPO_ID = r"^[a-z0-9][a-z0-9-]{0,63}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartRunIn(StrictModel):
    detect_reruns: int | None = Field(default=None, ge=10, le=100)
    verify_reruns: int | None = Field(default=None, ge=50, le=600)


class RepoOut(BaseModel):
    id: str
    name: str
    description: str
    source: str = "demo"
    owner: str | None = None
    html_url: str | None = None
    is_private: bool = False
    is_personal: bool = True
    workspace_id: str | None = None
    commit_sha: str | None = None
    prepare_status: str = "ready"
    prepare_error: str | None = None
    test_count: int
    last_scan_at: datetime | None
    last_result: str | None
    last_prepared_at: datetime | None = None
    default_branch: str | None = None


class ImportRepoIn(StrictModel):
    url: str = Field(min_length=15, max_length=300)
    personal: bool = True


class ImportGithubRepoIn(StrictModel):
    owner: str = Field(min_length=1, max_length=39)
    name: str = Field(min_length=1, max_length=100)
    personal: bool = True


class ImportRepoOut(RepoOut):
    already_imported: bool = False


class RunSummary(BaseModel):
    id: str
    repo_id: str
    status: str
    config: dict[str, Any]
    steps: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None = None
    cost_usd: float
    flake_count: int = 0
    broken_count: int = 0


class RunStarted(BaseModel):
    run_id: str


class FlakeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    run_id: str
    test_id: str
    state: str
    category: str | None
    fail_count: int
    run_count: int
    rate: float
    ci_low: float
    ci_high: float
    confidence_raw: float | None
    confidence_cal: float | None
    routing: str | None
    polluters: list | None = None


class CursorPage(BaseModel):
    items: list[RunSummary]
    next_cursor: str | None


RunStatus = Literal[
    "queued", "running", "clean", "completed", "cancelled", "failed",
    "interrupted", "stopped_budget", "stopped_time",
]
