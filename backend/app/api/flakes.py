"""Flake detail, plus the patch and evidence-bundle downloads."""
import json

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentSession, current_session, get_db, get_settings_dep
from app.config import Settings
from app.db.models import (
    AuditItem,
    Diagnosis,
    Escalation,
    Evidence,
    Flake,
    Patch,
    Reference,
    Repo,
    Run,
    RunEvent,
    Verification,
)
from app.errors import ApiError
from app.schemas.auth import UUID_PATTERN
from app.security.ratelimit import limiter
from app.services import github_prs
from app.services.repos_access import PRIVATE_SOURCE, PUBLIC_SOURCE, get_visible_flake

router = APIRouter(prefix="/flakes", tags=["flakes"])


class FlakeDetail(BaseModel):
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
    polluters: list | None
    bisection: dict | None
    error: str | None
    research_note: str | None = None
    evidence: dict | None
    references: list
    diagnoses: list
    patches: list
    escalation: dict | None
    audit: dict | None
    pull_request: dict | None = None


RESEARCH_NOTES = frozenset({"No upstream references found", "Search unavailable"})


def research_note(payloads: list[dict]) -> str | None:
    for payload in payloads:
        message = (payload or {}).get("message")
        if message in RESEARCH_NOTES:
            return message
    return None


def _verification(row: Verification | None) -> dict | None:
    if row is None:
        return None
    return {
        "reruns": row.reruns,
        "failures": row.failures,
        "ub95": row.ub95,
        "power_ok": row.power_ok,
        "full_suite_passed": row.full_suite_passed,
        "regressions": row.regressions or [],
        "outcome": row.outcome,
    }


@router.get("/{flake_id}", response_model=FlakeDetail)
async def get_flake(
    flake_id: str = Path(pattern=UUID_PATTERN),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> FlakeDetail:
    flake = await get_visible_flake(db, flake_id, session.user.id)
    evidence = await db.get(Evidence, flake.id)
    references = list(await db.scalars(
        select(Reference).where(Reference.flake_id == flake.id)
    ))
    diagnoses = list(await db.scalars(
        select(Diagnosis).where(Diagnosis.flake_id == flake.id).order_by(Diagnosis.attempt)
    ))
    patches = list(await db.scalars(
        select(Patch).where(Patch.flake_id == flake.id).order_by(Patch.attempt)
    ))
    checks = []
    if patches:
        checks = list(await db.scalars(
            select(Verification).where(Verification.patch_id.in_([row.id for row in patches]))
        ))
    by_patch = {row.patch_id: row for row in checks}
    escalation = await db.scalar(
        select(Escalation).where(Escalation.flake_id == flake.id)
        .order_by(Escalation.created_at.desc())
    )
    audit = await db.scalar(select(AuditItem).where(AuditItem.flake_id == flake.id))
    logs = list(await db.scalars(
        select(RunEvent).where(RunEvent.run_id == flake.run_id, RunEvent.type == "log.line")
        .order_by(RunEvent.seq.desc()).limit(300)
    ))
    note = research_note([
        row.payload for row in logs if (row.payload or {}).get("flake_id") == flake.id
    ])
    run = await db.get(Run, flake.run_id)
    repo = await db.get(Repo, run.repo_id) if run is not None else None
    verified = any(
        (by_patch.get(row.id) and by_patch[row.id].outcome == "verified")
        for row in patches
    )
    pr_hint = {
        "show": bool(
            repo
            and repo.source in {PUBLIC_SOURCE, PRIVATE_SOURCE}
            and flake.routing == "auto_pr"
            and verified
        ),
        "repo_full_name": (
            f"{repo.owner}/{repo.name}" if repo and repo.owner and repo.name else None
        ),
    }
    return FlakeDetail(
        id=flake.id,
        run_id=flake.run_id,
        test_id=flake.test_id,
        state=flake.state,
        category=flake.category,
        fail_count=flake.fail_count,
        run_count=flake.run_count,
        rate=flake.rate,
        ci_low=flake.ci_low,
        ci_high=flake.ci_high,
        confidence_raw=flake.confidence_raw,
        confidence_cal=flake.confidence_cal,
        routing=flake.routing,
        polluters=flake.polluters,
        bisection=flake.bisection,
        error=flake.error,
        research_note=note,
        evidence=None if evidence is None else {
            "failing_samples": evidence.failing_samples or [],
            "passing_samples": evidence.passing_samples or [],
        },
        references=[
            {
                "title": row.title, "url": row.url, "site": row.site,
                "snippet": row.snippet, "matched": row.matched,
            }
            for row in references
        ],
        diagnoses=[
            {
                "attempt": row.attempt, "root_cause": row.root_cause,
                "mechanism": row.mechanism, "culprit": row.culprit,
                "category": row.category, "fix_strategy": row.fix_strategy,
                "needs_human": row.needs_human, "self_confidence": row.self_confidence,
                "agreement_k": row.agreement_k, "agreement_n": row.agreement_n,
            }
            for row in diagnoses
        ],
        patches=[
            {
                "id": row.id, "attempt": row.attempt, "diff": row.diff,
                "summary": row.summary, "status": row.status,
                "violations": row.violations or [], "files_changed": row.files_changed or [],
                "lines_changed": row.lines_changed,
                "verification": _verification(by_patch.get(row.id)),
            }
            for row in patches
        ],
        escalation=None if escalation is None else {
            "id": escalation.id, "provider": escalation.provider,
            "status": escalation.status, "reason": escalation.reason,
            "response": escalation.response, "external_ref": escalation.external_ref,
            "created_at": escalation.created_at.isoformat() + "Z",
            "updated_at": escalation.updated_at.isoformat() + "Z",
        },
        audit=None if audit is None else {
            "consensus": audit.consensus, "agreement": audit.agreement,
            "is_control": audit.is_control,
        },
        pull_request=pr_hint,
    )


@router.get("/{flake_id}/pull-request")
async def preview_pull_request(
    flake_id: str = Path(pattern=UUID_PATTERN),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    preview = await github_prs.preview_pull_request(
        db, settings, session.user.id, flake_id,
    )
    return {
        "can_create": preview.can_create,
        "disabled_reason": preview.disabled_reason,
        "owner": preview.owner,
        "name": preview.name,
        "full_name": preview.full_name,
        "branch": preview.branch,
        "title": preview.title,
        "body": preview.body,
        "base_branch": preview.base_branch,
        "scanned_sha": preview.scanned_sha,
        "default_moved": preview.default_moved,
    }


@router.post("/{flake_id}/pull-request")
@limiter.limit("10/hour")
async def open_pull_request(
    request: Request,
    flake_id: str = Path(pattern=UUID_PATTERN),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    return await github_prs.create_pull_request(
        db, settings, session.user.id, flake_id,
    )


@router.get("/{flake_id}/patch")
async def download_patch(
    flake_id: str = Path(pattern=UUID_PATTERN),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> Response:
    flake = await get_visible_flake(db, flake_id, session.user.id)
    patches = list(await db.scalars(
        select(Patch).where(Patch.flake_id == flake.id).order_by(Patch.attempt.desc())
    ))
    chosen = next((row for row in patches if row.status == "verified"), None)
    if chosen is None:
        chosen = next((row for row in patches if row.status == "proposed"), None)
    if chosen is None and patches:
        chosen = patches[0]
    if chosen is None or not chosen.diff:
        raise ApiError(404, "patch_not_found", "This flake has no patch to download.")
    return Response(
        content=chosen.diff,
        media_type="text/x-diff",
        headers={"Content-Disposition": 'attachment; filename="patch.diff"'},
    )


@router.get("/{flake_id}/bundle")
async def download_bundle(
    flake_id: str = Path(pattern=UUID_PATTERN),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> Response:
    flake = await get_visible_flake(db, flake_id, session.user.id)
    row = await db.scalar(
        select(Escalation).where(Escalation.flake_id == flake.id)
        .order_by(Escalation.created_at.desc())
    )
    if row is None:
        raise ApiError(404, "bundle_not_found", "This flake has no evidence bundle.")
    return Response(
        content=json.dumps(row.bundle, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="bundle.json"'},
    )
