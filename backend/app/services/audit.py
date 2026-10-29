"""Create an audit batch, apply labels, and store a calibration version."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import (
    AuditBatch,
    AuditItem,
    CalibrationVersion,
    Diagnosis,
    Evidence,
    Flake,
    Patch,
)
from app.integrations.audit.batch import build_items, clip_excerpt
from app.integrations.audit.csv_import import CsvError, parse_labels
from app.integrations.audit.toloka import TolokaProvider
from app.integrations.escalation.base import ProviderError, ProviderUnavailable
from app.security.redact import redact
from app.services.calibration import (
    consensus,
    control_accuracy,
    fit_labels,
    label_pairs,
    operating_point,
    reliability_bins,
)

PARTIAL_MESSAGE = "Using the default threshold until {count} labels are in."


def _controls(count: int) -> list[dict]:
    templates = [item for item in build_items() if item["is_control"]]
    if count <= 0 or not templates:
        return []
    return [templates[index % len(templates)] for index in range(count)]


async def create_batch(
    session: AsyncSession, settings: Settings, flake_ids: list[str], created_by: str | None,
) -> AuditBatch:
    real = await _real_items(session, flake_ids)
    control_count = max(1, round(len(real) / 4)) if real else 0
    controls = _controls(control_count)
    items = real + controls
    if not items:
        items = build_items()
    provider = "toloka" if settings.audit_provider == "toloka" else "csv_import"
    batch = AuditBatch(
        provider=provider,
        status="local",
        item_count=len(items),
        labelled_count=0,
        created_by=created_by,
    )
    session.add(batch)
    await session.flush()
    for item in items:
        session.add(AuditItem(
            batch_id=batch.id,
            flake_id=item.get("flake_id"),
            diagnosis_id=item.get("diagnosis_id"),
            patch_id=item.get("patch_id"),
            is_control=bool(item["is_control"]),
            expected_label=item.get("expected_label"),
            payload={
                "item_id": item["item_id"],
                "test_id": item.get("test_id"),
                "failure_excerpt": item.get("failure_excerpt"),
                "diagnosis": item.get("diagnosis"),
                "diff": item.get("diff"),
            },
            labels=[],
            confidence_raw=item.get("confidence_raw"),
        ))
    await session.flush()
    return batch


async def _real_items(session: AsyncSession, flake_ids: list[str]) -> list[dict]:
    rows = []
    for flake_id in flake_ids:
        flake = await session.get(Flake, flake_id)
        if flake is None:
            continue
        diagnosis = await session.scalar(
            select(Diagnosis).where(Diagnosis.flake_id == flake.id, Diagnosis.attempt == 1)
        )
        evidence = await session.get(Evidence, flake.id)
        patch = await session.scalar(
            select(Patch).where(Patch.flake_id == flake.id).order_by(Patch.attempt.desc())
        )
        sample = ""
        if evidence and evidence.failing_samples:
            first = evidence.failing_samples[0]
            sample = first.get("traceback") or "" if isinstance(first, dict) else ""
        rows.append({
            "item_id": flake.id,
            "flake_id": flake.id,
            "diagnosis_id": diagnosis.id if diagnosis else None,
            "patch_id": patch.id if patch else None,
            "is_control": False,
            "expected_label": None,
            "test_id": flake.test_id,
            "failure_excerpt": clip_excerpt(sample),
            "diagnosis": redact(diagnosis.root_cause if diagnosis else ""),
            "diff": redact((patch.diff if patch else "") or "")[:8000],
            "confidence_raw": flake.confidence_raw,
        })
    return rows


async def apply_csv(session: AsyncSession, settings: Settings, raw: bytes) -> AuditBatch:
    parsed = parse_labels(raw)
    batch = await session.scalar(select(AuditBatch).order_by(AuditBatch.created_at.desc()))
    if batch is None:
        raise CsvError("Import a batch before uploading labels.")
    items = list(await session.scalars(select(AuditItem).where(AuditItem.batch_id == batch.id)))
    by_key = {(item.payload or {}).get("item_id"): item for item in items}
    grouped: dict[str, list[dict]] = {}
    for row in parsed:
        if row["item_id"] not in by_key:
            raise CsvError("A row names an item that is not in this batch.")
        grouped.setdefault(row["item_id"], []).append({"q1": row["q1"], "q2": row["q2"]})
    for item_id, answers in grouped.items():
        item = by_key[item_id]
        item.labels = answers
        agreed, agreement = consensus(answers)
        item.consensus = agreed
        item.agreement = agreement
    _refresh_batch(batch, items)
    await _store_fit(session, settings, items)
    return batch


def _refresh_batch(batch: AuditBatch, items: list[AuditItem]) -> None:
    labelled = sum(1 for item in items if item.labels)
    batch.labelled_count = labelled
    batch.control_accuracy = control_accuracy([
        (item.is_control, item.expected_label, item.consensus) for item in items
    ])
    batch.status = "partial" if labelled else "local"


async def _store_fit(
    session: AsyncSession, settings: Settings, items: list[AuditItem],
    *, actor: str | None = None, manual: tuple[float, str] | None = None,
) -> CalibrationVersion | None:
    pairs = label_pairs(items)
    if not pairs and manual is None:
        return None
    fitted = fit_labels(
        pairs, min_labels=settings.calibration_min_labels,
        default_threshold=settings.confidence_threshold_default,
    )
    previous = await session.scalar(
        select(CalibrationVersion).order_by(CalibrationVersion.created_at.desc())
    )
    method = "isotonic"
    threshold = fitted["threshold"]
    reason = None
    created_by = actor
    if manual is not None:
        method = "manual"
        threshold, reason = manual
        created_by = actor
    elif previous is not None and previous.method == "manual":
        method = "manual"
        threshold = previous.threshold
        reason = previous.reason
        created_by = previous.created_by
    version = CalibrationVersion(
        method=method,
        points=fitted["points"],
        threshold=threshold,
        precision_at=fitted["precision_at"],
        coverage_at=fitted["coverage_at"],
        n_labels=fitted["n_labels"],
        reason=reason,
        created_by=created_by,
    )
    session.add(version)
    await session.flush()
    return version


async def set_threshold(
    session: AsyncSession, settings: Settings, threshold: float, reason: str, actor: str,
) -> CalibrationVersion:
    items = list(await session.scalars(select(AuditItem)))
    pairs = label_pairs(items)
    fitted = fit_labels(
        pairs, min_labels=settings.calibration_min_labels,
        default_threshold=settings.confidence_threshold_default,
    )
    version = CalibrationVersion(
        method="manual",
        points=fitted["points"],
        threshold=threshold,
        precision_at=fitted["precision_at"],
        coverage_at=fitted["coverage_at"],
        n_labels=fitted["n_labels"],
        reason=reason,
        created_by=actor,
    )
    session.add(version)
    await session.flush()
    return version


async def sync_batch(session: AsyncSession, settings: Settings, batch_id: str) -> dict:
    batch = await session.get(AuditBatch, batch_id)
    if batch is None:
        return {"found": False}
    provider = TolokaProvider(settings)
    try:
        probe = await provider.probe()
    except (ProviderUnavailable, ProviderError) as exc:
        probe = {"configured": settings.toloka_api_key is not None, "reason": type(exc).__name__}
    run_id = probe.get("run_id")
    statuses: list[dict] = []
    if run_id:
        try:
            statuses = await provider.fetch(str(run_id))
            batch.external_ref = str(run_id)
        except (ProviderUnavailable, ProviderError) as exc:
            probe["fetch"] = type(exc).__name__
    completed = sum(1 for row in statuses if row.get("status") == "completed")
    # The run-item payload has status only. Reviewer answers arrive through CSV import.
    probe["items_seen"] = len(statuses)
    probe["completed"] = completed
    probe["annotations"] = False
    batch.status = "partial" if batch.labelled_count else "local"
    return {"found": True, "batch_id": batch.id, "probe": _public_probe(probe)}


def _public_probe(probe: dict) -> dict:
    """Counts and reasons only. Run ids and response bodies stay on the server."""
    return {
        "configured": bool(probe.get("configured")),
        "projects": probe.get("projects"),
        "runs": probe.get("runs"),
        "reason": probe.get("reason"),
        "items_seen": probe.get("items_seen", 0),
        "completed": probe.get("completed", 0),
        "annotations": False,
    }


async def calibration_view(session: AsyncSession, settings: Settings) -> dict:
    version = await session.scalar(
        select(CalibrationVersion).order_by(CalibrationVersion.created_at.desc())
    )
    items = list(await session.scalars(select(AuditItem)))
    pairs = label_pairs(items)
    fitted = fit_labels(
        pairs, min_labels=settings.calibration_min_labels,
        default_threshold=settings.confidence_threshold_default,
    )
    source = fitted["source"]
    threshold = fitted["threshold"]
    message = fitted["message"]
    partial = fitted["partial"]
    if version is not None and version.method == "manual":
        source = "manual"
        threshold = version.threshold
        message = "Threshold set by the workspace owner."
        partial = version.n_labels < settings.calibration_min_labels
    precision, coverage = operating_point(pairs, threshold)
    batches = list(await session.scalars(
        select(AuditBatch).order_by(AuditBatch.created_at.desc()).limit(20)
    ))
    return {
        "source": source,
        "partial": partial,
        "threshold": threshold,
        "suggested_threshold": fitted["suggested_threshold"],
        "precision_at": precision,
        "coverage_at": coverage,
        "n_labels": fitted["n_labels"],
        "min_labels": settings.calibration_min_labels,
        "message": message,
        "points": fitted["points"],
        "reliability": fitted["reliability"] or reliability_bins([]),
        "batches": [
            {
                "id": batch.id,
                "provider": batch.provider,
                "external_ref": batch.external_ref,
                "status": batch.status,
                "item_count": batch.item_count,
                "labelled_count": batch.labelled_count,
                "control_accuracy": batch.control_accuracy,
                "created_at": batch.created_at,
            }
            for batch in batches
        ],
    }


def threshold_ok(value: float) -> bool:
    if value < 0.50 or value > 0.95:
        return False
    steps = round(value * 100)
    return steps % 5 == 0 and abs(value * 100 - steps) < 1e-6
