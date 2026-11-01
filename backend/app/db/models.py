import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import DATETIME, MEDIUMTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_failed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    locked_until: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    sessions_valid_after: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))


class RevokedSession(Base):
    __tablename__ = "revoked_sessions"

    jti: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (Index("ix_workspaces_created_by", "created_by"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
        Index("ix_workspace_members_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("workspaces.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)


class WorkspaceInvite(Base):
    __tablename__ = "workspace_invites"
    __table_args__ = (
        UniqueConstraint("token", name="uq_workspace_invites_token"),
        Index("ix_workspace_invites_email", "email"),
        Index("ix_workspace_invites_workspace_id", "workspace_id"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("workspaces.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(60))
    last_name: Mapped[str | None] = mapped_column(String(60))
    token: Mapped[str] = mapped_column(String(64), nullable=False)
    invited_by: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    accepted_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("users.id"))


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_user_unread", "user_id", "read_at"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    link: Mapped[str | None] = mapped_column(String(512))
    data: Mapped[dict | None] = mapped_column(JSON)
    read_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)


class SecurityLog(Base):
    __tablename__ = "security_log"
    __table_args__ = (Index("ix_security_log_created_at", "created_at"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_hash: Mapped[str | None] = mapped_column(String(64))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)


class GithubAccount(Base):
    __tablename__ = "github_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_github_accounts_user_id"),
        UniqueConstraint("github_user_id", name="uq_github_accounts_github_user_id"),
        Index("ix_github_accounts_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id"), nullable=False)
    github_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    login: Mapped[str] = mapped_column(String(64), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    scopes: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))


class Repo(Base):
    __tablename__ = "repos"
    __table_args__ = (
        Index("ix_repos_source", "source"),
        Index("ix_repos_created_by", "created_by"),
        Index("ix_repos_prepare_status", "prepare_status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="demo")
    owner: Mapped[str | None] = mapped_column(String(64))
    default_branch: Mapped[str | None] = mapped_column(String(255))
    html_url: Mapped[str | None] = mapped_column(String(512))
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    github_account_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("github_accounts.id"),
    )
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    test_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    editable_paths: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    prepare_status: Mapped[str] = mapped_column(String(24), nullable=False, default="ready")
    prepare_error: Mapped[str | None] = mapped_column(MEDIUMTEXT)
    last_prepared_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("users.id"))
    is_personal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    workspace_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("workspaces.id"))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_repo_status", "repo_id", "status"),
        Index("ix_runs_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    repo_id: Mapped[str] = mapped_column(String(64), ForeignKey("repos.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    steps: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    last_event_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("runs.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)


class TestOutcome(Base):
    __tablename__ = "test_outcomes"
    __table_args__ = (Index("ix_test_outcomes_run_test", "run_id", "test_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("runs.id"), nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False, default="detect")
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    test_id: Mapped[str] = mapped_column(String(300), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    hash_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class Flake(Base):
    __tablename__ = "flakes"
    __table_args__ = (Index("ix_flakes_run", "run_id"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("runs.id"), nullable=False)
    test_id: Mapped[str] = mapped_column(String(300), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    category: Mapped[str | None] = mapped_column(String(32))
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rate: Mapped[float] = mapped_column(Float, nullable=False)
    ci_low: Mapped[float] = mapped_column(Float, nullable=False)
    ci_high: Mapped[float] = mapped_column(Float, nullable=False)
    polluters: Mapped[list | None] = mapped_column(JSON)
    bisection: Mapped[dict | None] = mapped_column(JSON)
    confidence_raw: Mapped[float | None] = mapped_column(Float)
    confidence_cal: Mapped[float | None] = mapped_column(Float)
    routing: Mapped[str | None] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow,
                                                 onupdate=utcnow)


class Evidence(Base):
    __tablename__ = "evidence"

    flake_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("flakes.id"), primary_key=True)
    failing_samples: Mapped[list] = mapped_column(JSON, nullable=False)
    passing_samples: Mapped[list] = mapped_column(JSON, nullable=False)


class Reference(Base):
    __tablename__ = "references"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    flake_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("flakes.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    site: Mapped[str] = mapped_column(String(255), nullable=False)
    snippet: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    score: Mapped[float | None] = mapped_column(Float)
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    flake_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("flakes.id"), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    mechanism: Mapped[str] = mapped_column(Text, nullable=False)
    culprit: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    fix_strategy: Mapped[str] = mapped_column(Text, nullable=False)
    needs_human: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    self_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    agreement_k: Mapped[int] = mapped_column(Integer, nullable=False)
    agreement_n: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)


class Patch(Base):
    __tablename__ = "patches"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    flake_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("flakes.id"), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    diff: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="proposed")
    violations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    files_changed: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    lines_changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    patch_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("patches.id"), nullable=False)
    reruns: Mapped[int] = mapped_column(Integer, nullable=False)
    failures: Mapped[int] = mapped_column(Integer, nullable=False)
    ub95: Mapped[float | None] = mapped_column(Float)
    power_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    full_suite_passed: Mapped[bool | None] = mapped_column(Boolean)
    regressions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)


class Escalation(Base):
    __tablename__ = "escalations"
    __table_args__ = (Index("ix_escalations_status", "status"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    flake_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("flakes.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="submitted")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    bundle: Mapped[dict] = mapped_column(JSON, nullable=False)
    response: Mapped[str | None] = mapped_column(MEDIUMTEXT)
    attempts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow,
                                                 onupdate=utcnow)


class AuditBatch(Base):
    __tablename__ = "audit_batches"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    labelled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    control_accuracy: Mapped[float | None] = mapped_column(Float)
    created_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)


class AuditItem(Base):
    __tablename__ = "audit_items"
    __table_args__ = (Index("ix_audit_items_batch", "batch_id"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("audit_batches.id"), nullable=False)
    flake_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("flakes.id"))
    diagnosis_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("diagnoses.id"))
    patch_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("patches.id"))
    is_control: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expected_label: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    labels: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    consensus: Mapped[str | None] = mapped_column(String(16))
    agreement: Mapped[float | None] = mapped_column(Float)
    confidence_raw: Mapped[float | None] = mapped_column(Float)


class CalibrationVersion(Base):
    __tablename__ = "calibration_versions"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    points: Mapped[list] = mapped_column(JSON, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    precision_at: Mapped[float | None] = mapped_column(Float)
    coverage_at: Mapped[float | None] = mapped_column(Float)
    n_labels: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)


class LlmCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_run", "run_id"),
        Index("ix_llm_calls_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    run_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("runs.id"))
    flake_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("flakes.id"))
    node: Mapped[str] = mapped_column(String(32), nullable=False)
    tier: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)


class SearchCache(Base):
    """Tavily results keyed by query hash. Rows older than 24 hours are refreshed."""

    __tablename__ = "search_cache"

    query_hash: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    query: Mapped[str] = mapped_column(String(200), nullable=False)
    results: Mapped[list] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)


class WorkspaceDefaults(Base):
    """Single-row workspace preferences that override env defaults for new scans."""

    __tablename__ = "workspace_defaults"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    detect_reruns: Mapped[int] = mapped_column(Integer, nullable=False)
    verify_reruns: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("users.id"))
