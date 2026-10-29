"""Build an evidence bundle, submit it once, and poll provider status."""
import json

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import (
    Diagnosis,
    Escalation,
    Evidence,
    Flake,
    Patch,
    Reference,
    Verification,
    utcnow,
)
from app.graph.text import untrusted
from app.integrations.escalation import build_provider
from app.integrations.escalation.base import ProviderError, StatusResult, SubmitResult
from app.integrations.escalation.local import LocalProvider
from app.llm.factory import Llm
from app.llm.prompts import prompt
from app.security.redact import redact, redact_obj

log = structlog.get_logger()

POLL_SECONDS = 300
_QUESTION = (
    "What is the smallest change that removes this failure "
    "without hiding the behaviour the test checks?"
)


def split_summary(text: str) -> tuple[str, str]:
    question = ""
    kept: list[str] = []
    for line in (text or "").splitlines():
        if line.strip().lower().startswith("question:"):
            question = line.split(":", 1)[1].strip()
        else:
            kept.append(line)
    summary = redact("\n".join(kept).strip() or (text or "").strip())
    return summary, redact(question or _QUESTION)


def render_bundle(bundle: dict) -> str:
    rate = bundle.get("failure_rate") or {}
    lines = [
        f"{bundle.get('app') or 'Deflake'} evidence bundle",
        "",
        str(bundle.get("summary") or ""),
        "",
        f"Test: {bundle.get('test_id')}",
        f"Category: {bundle.get('category')}",
        (
            f"Failure rate: {rate.get('rate')} "
            f"(95% interval {rate.get('ci_low')} to {rate.get('ci_high')}, "
            f"{rate.get('fail_count')} of {rate.get('run_count')})"
        ),
        f"Reason: {bundle.get('reason')}",
        "",
        f"Polluter: {json.dumps(bundle.get('polluter'), default=str)[:2000]}",
        "",
        "References:",
    ]
    for ref in bundle.get("references") or []:
        lines.append(f"- {ref.get('title')} {ref.get('url')}")
    lines.extend(["", "Patch attempts:"])
    for row in bundle.get("patches") or []:
        violations = json.dumps(row.get("violations"), default=str)[:500]
        lines.append(
            f"- attempt {row.get('attempt')} {row.get('status')} violations={violations}"
        )
    verification = bundle.get("verification") or {}
    lines.extend([
        "",
        (
            "Verification: "
            f"outcome={verification.get('outcome')} reruns={verification.get('reruns')} "
            f"failures={verification.get('failures')} power_ok={verification.get('power_ok')} "
            f"suite_passed={verification.get('full_suite_passed')}"
        ),
        "",
        "Failing samples:",
        json.dumps(bundle.get("failing_samples"), default=str)[:4000],
        "",
        "Passing samples:",
        json.dumps(bundle.get("passing_samples"), default=str)[:2000],
        "",
        f"Question: {bundle.get('question')}",
    ])
    return "\n".join(lines)


def _clips(samples: list | None, limit: int = 3) -> list:
    clipped = []
    for sample in redact_obj(samples or [])[:limit]:
        if isinstance(sample, dict) and isinstance(sample.get("traceback"), str):
            sample = dict(sample)
            sample["traceback"] = sample["traceback"][:1500]
        clipped.append(sample)
    return clipped


def _reason(flake: Flake, diagnosis: Diagnosis | None, verification: Verification | None,
            threshold: float) -> str:
    if flake.category == "environment":
        return "Category is environment, so this needs a product decision."
    if diagnosis is not None and diagnosis.needs_human:
        return "The diagnosis asked for a human."
    if verification is not None and verification.outcome != "verified":
        return f"Verification was {verification.outcome}."
    score = flake.confidence_cal if flake.confidence_cal is not None else flake.confidence_raw
    if score is not None:
        return f"Confidence {score:.3f} is below {threshold:.2f}."
    return "Routed to a human expert."


def _attempt(provider: str, ok: bool, error: Exception | None = None,
             external_ref: str | None = None) -> dict:
    row = {"provider": provider, "ok": ok}
    if external_ref:
        row["external_ref"] = external_ref
    if error is not None:
        row["error"] = type(error).__name__
        row["detail"] = redact(str(error))[:200]
    return row


async def deliver(
    bundle: dict, idempotency_key: str, primary, fallback,
) -> tuple[SubmitResult, list]:
    """Try the primary provider twice, then the fallback, then local."""
    attempts: list[dict] = []
    result = await _try(primary, bundle, idempotency_key, attempts, times=2)
    if result is not None:
        return result, attempts
    if fallback.name != primary.name:
        result = await _try(fallback, bundle, idempotency_key, attempts, times=1)
        if result is not None:
            return result, attempts
    if primary.name != "local" and fallback.name != "local":
        result = await _try(LocalProvider(), bundle, idempotency_key, attempts, times=1)
        if result is not None:
            return result, attempts
    raise ProviderError("every escalation provider failed")


async def _try(
    provider, bundle, idempotency_key, attempts: list, times: int,
) -> SubmitResult | None:
    result = None
    for _ in range(times):
        try:
            result = await provider.submit(bundle, idempotency_key)
        except Exception as exc:
            attempts.append(_attempt(provider.name, False, exc))
            continue
        attempts.append(_attempt(provider.name, True, external_ref=result.external_ref))
        return result
    return None


async def build_bundle(session: AsyncSession, settings: Settings, llm: Llm, flake: Flake) -> dict:
    diagnosis = await session.scalar(
        select(Diagnosis).where(Diagnosis.flake_id == flake.id, Diagnosis.attempt == 1)
    )
    evidence = await session.get(Evidence, flake.id)
    references = list(await session.scalars(
        select(Reference).where(Reference.flake_id == flake.id)
    ))
    patches = list(await session.scalars(
        select(Patch).where(Patch.flake_id == flake.id).order_by(Patch.attempt)
    ))
    verification = None
    for row in reversed(patches):
        verification = await session.scalar(
            select(Verification).where(Verification.patch_id == row.id)
        )
        if verification is not None:
            break
    reason = _reason(flake, diagnosis, verification, settings.confidence_threshold_default)
    digest = _digest(flake, diagnosis, verification, patches, reason)
    summary, question, source = await _summary(settings, llm, flake, digest)
    bundle = {
        "app": settings.app_name,
        "summary": summary,
        "summary_source": source,
        "question": question,
        "test_id": flake.test_id,
        "category": flake.category,
        "reason": reason,
        "confidence": {"raw": flake.confidence_raw, "calibrated": flake.confidence_cal},
        "failure_rate": {
            "rate": flake.rate,
            "ci_low": flake.ci_low,
            "ci_high": flake.ci_high,
            "fail_count": flake.fail_count,
            "run_count": flake.run_count,
        },
        "failing_samples": _clips(evidence.failing_samples if evidence else []),
        "passing_samples": _clips(evidence.passing_samples if evidence else []),
        "polluter": redact_obj(flake.bisection if flake.bisection is not None else flake.polluters),
        "references": [
            {
                "title": redact(row.title),
                "url": row.url,
                "snippet": redact(row.snippet),
                "matched": row.matched,
            }
            for row in references
        ],
        "patches": [
            {
                "attempt": row.attempt,
                "status": row.status,
                "summary": redact(row.summary),
                "violations": redact_obj(row.violations or []),
                "lines_changed": row.lines_changed,
                "diff": redact(row.diff or "")[:4000],
            }
            for row in patches
        ],
        "verification": None if verification is None else {
            "outcome": verification.outcome,
            "reruns": verification.reruns,
            "failures": verification.failures,
            "ub95": verification.ub95,
            "power_ok": verification.power_ok,
            "full_suite_passed": verification.full_suite_passed,
            "regressions": _clips(verification.regressions, limit=10),
        },
    }
    bundle["text"] = render_bundle(bundle)
    return bundle


def _digest(flake, diagnosis, verification, patches, reason: str) -> str:
    lines = [
        f"test_id: {flake.test_id}",
        f"category: {flake.category}",
        (
            f"failure_rate: {flake.rate} interval {flake.ci_low} to {flake.ci_high} "
            f"({flake.fail_count} of {flake.run_count})"
        ),
        f"reason: {reason}",
    ]
    if diagnosis is not None:
        lines.append(f"root_cause: {diagnosis.root_cause}")
        lines.append(f"mechanism: {diagnosis.mechanism}")
        lines.append(f"fix_strategy: {diagnosis.fix_strategy}")
    if verification is not None:
        lines.append(
            f"verification: {verification.outcome} "
            f"failures={verification.failures} reruns={verification.reruns}"
        )
    for row in patches:
        lines.append(f"patch attempt {row.attempt}: {row.status}")
    return "\n".join(lines)


async def _summary(settings: Settings, llm: Llm, flake: Flake, digest: str) -> tuple[str, str, str]:
    version, body = prompt("escalate")
    try:
        text = await llm.complete(
            [
                {"role": "system", "content": body},
                {"role": "user", "content": untrusted(digest)},
            ],
            tier="balanced",
            node="escalate",
            temperature=0.2,
            run_id=flake.run_id,
            flake_id=flake.id,
            prompt_version=version,
        )
    except Exception as exc:
        log.warning("escalation_summary_failed", error=type(exc).__name__)
        fallback = (
            f"The test {flake.test_id} ({flake.category}) failed "
            f"{flake.fail_count} of {flake.run_count} times. {digest}"
        )
        summary, question = split_summary(fallback)
        return summary, question, "local"
    summary, question = split_summary(text)
    source = "super" if settings.ai_provider != "fake" else "fake"
    return summary, question, source


async def submit_flake(session: AsyncSession, settings: Settings, llm: Llm,
                       flake: Flake) -> tuple[Escalation, bool]:
    """Return the escalation row and whether this call created it."""
    key = f"{flake.id}:1"
    existing = await session.scalar(select(Escalation).where(Escalation.idempotency_key == key))
    if existing is not None and existing.external_ref:
        return existing, False
    bundle = await build_bundle(session, settings, llm, flake)
    primary = build_provider(settings, settings.escalation_provider)
    fallback = build_provider(settings, settings.escalation_fallback)
    result, attempts = await deliver(bundle, key, primary, fallback)
    if existing is None:
        existing = Escalation(
            flake_id=flake.id,
            idempotency_key=key,
            provider=result.provider,
            external_ref=result.external_ref,
            status=result.status,
            reason=bundle["reason"],
            bundle=bundle,
            attempts=attempts,
        )
        try:
            async with session.begin_nested():
                session.add(existing)
                await session.flush()
        except IntegrityError:
            found = await session.scalar(
                select(Escalation).where(Escalation.idempotency_key == key)
            )
            if found is None:
                raise
            return found, False
        return existing, True
    existing.provider = result.provider
    existing.external_ref = result.external_ref
    existing.status = result.status
    existing.reason = bundle["reason"]
    existing.bundle = bundle
    existing.attempts = attempts
    existing.updated_at = utcnow()
    await session.flush()
    return existing, True


async def refresh_escalation(
    session: AsyncSession, settings: Settings, row: Escalation,
) -> Escalation:
    if not row.external_ref:
        return row
    provider = build_provider(settings, row.provider)
    result: StatusResult = await provider.status(row.external_ref)
    row.status = result.status
    if result.response:
        row.response = redact(result.response)[:16000]
    row.updated_at = utcnow()
    return row


async def poll_open(sessionmaker, settings: Settings) -> None:
    async with sessionmaker() as session:
        rows = list(await session.scalars(
            select(Escalation).where(Escalation.status.in_(("submitted", "in_progress")))
        ))
        changed = False
        for row in rows:
            if not row.external_ref:
                continue
            try:
                await refresh_escalation(session, settings, row)
                changed = True
            except Exception as exc:
                log.warning(
                    "escalation_poll_error", provider=row.provider, error=type(exc).__name__,
                )
        if changed:
            await session.commit()


def provider_label(row: Escalation) -> str:
    failed = [item for item in (row.attempts or []) if not item.get("ok")]
    if failed and row.provider != failed[0].get("provider"):
        return f"{row.provider} (fallback after {failed[0].get('provider')} failed)"
    return row.provider
