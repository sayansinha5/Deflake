"""Pool-adjacent-violators, threshold selection, CSV import, and the owner-only cutoff."""
import httpx
from sqlalchemy import select

from app.db.models import (
    AuditItem,
    Diagnosis,
    Evidence,
    Flake,
    Patch,
    Repo,
    Run,
    SecurityLog,
)
from app.graph.nodes.score import _threshold
from app.integrations.audit.toloka import TolokaProvider
from app.services.calibration import consensus, fit_labels, pav, suggest_threshold
from app.services.events import empty_steps
from tests.conftest import (
    CSRF,
    MEMBER_EMAIL,
    MEMBER_PASSWORD,
    OWNER_EMAIL,
    OWNER_PASSWORD,
    add_user,
    sign_in,
)
from tests.test_config import build

TEST_ID = "tests/test_pricing.py::test_convert_eur_to_usd"


def test_pav_pools_a_decrease_and_keeps_a_rise():
    points = pav([(0.1, 0), (0.2, 0), (0.3, 1), (0.4, 0), (0.9, 1)])
    assert points == [
        {"raw": 0.1, "calibrated": 0.0},
        {"raw": 0.2, "calibrated": 0.0},
        {"raw": 0.3, "calibrated": 0.5},
        {"raw": 0.4, "calibrated": 0.5},
        {"raw": 0.9, "calibrated": 1.0},
    ]


def test_threshold_is_the_lowest_score_with_precision_and_ten_items():
    pairs = [(0.4, 1 if index < 5 else 0) for index in range(10)]
    pairs += [(0.9, 1) for _ in range(10)]
    threshold, precision, coverage = suggest_threshold(pairs)
    assert threshold == 0.9
    assert precision == 1
    assert coverage == 0.5
    short = [(0.9, 1) for _ in range(5)]
    assert suggest_threshold(short) == (None, None, None)
    fitted = fit_labels(pairs, min_labels=30, default_threshold=0.8)
    assert fitted["partial"] is True
    assert fitted["threshold"] == 0.8
    assert fitted["n_labels"] == 20
    assert len(fitted["reliability"]) == 5


def test_a_tie_has_no_consensus():
    agreed, _agreement = consensus([
        {"q1": "Yes", "q2": "Real fix"},
        {"q1": "No", "q2": "Hides it"},
    ])
    assert agreed == "no_consensus"
    agreed, agreement = consensus([
        {"q1": "Yes", "q2": "Real fix"},
        {"q1": "Yes", "q2": "Real fix"},
        {"q1": "Unsure", "q2": "Unsure"},
    ])
    assert agreed == "1"
    assert agreement == 1


async def test_toloka_fetch_does_not_invent_answers():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2-beta/projects":
            return httpx.Response(200, json={"projects": []})
        if request.url.path == "/api/v2-beta/runs/run-1/items":
            return httpx.Response(200, json={"items": [{
                "datasetItemId": "dataset-item",
                "state": {"status": "completed"},
            }]})
        return httpx.Response(404, json={"message": "no"})

    settings = build(toloka_api_key="test-key", toloka_pipeline_id=None)
    provider = TolokaProvider(settings, transport=httpx.MockTransport(handler))
    probe = await provider.probe()
    assert probe["projects"] == 0
    assert probe["reason"] == "pipeline_not_configured"
    rows = await provider.fetch("run-1")
    assert rows == [{
        "dataset_item_id": "dataset-item", "status": "completed", "answers": [],
    }]


async def _flake(app) -> tuple[str, str]:
    async with app.state.sessionmaker() as db:
        if await db.get(Repo, "flaky-shop") is None:
            db.add(Repo(
                id="flaky-shop", name="flaky-shop", description="", path="flaky-shop",
                test_count=0, editable_paths=["shop/**"],
            ))
        run = Run(
            repo_id="flaky-shop", status="completed", config={}, steps=empty_steps(),
        )
        db.add(run)
        await db.flush()
        flake = Flake(
            run_id=run.id, test_id=TEST_ID, state="escalated", category="order_dependent",
            routing="escalate", fail_count=6, run_count=30, rate=0.2, ci_low=0.1, ci_high=0.4,
            confidence_raw=0.91, confidence_cal=0.91,
        )
        db.add(flake)
        await db.flush()
        db.add(Diagnosis(
            flake_id=flake.id, attempt=1, root_cause="A cache leaked.",
            mechanism="leftover rate", culprit="shop/pricing.py", category="order_dependent",
            fix_strategy="reset it", needs_human=False, self_confidence=0.8,
            agreement_k=3, agreement_n=3,
        ))
        db.add(Evidence(
            flake_id=flake.id,
            failing_samples=[{"traceback": "AssertionError: assert 50.0 == 110.0"}],
            passing_samples=[],
        ))
        db.add(Patch(
            flake_id=flake.id, attempt=1, diff="--- a/shop/pricing.py\n+++ b/shop/pricing.py\n",
            summary="reset", status="verified", lines_changed=4,
        ))
        await db.commit()
        return run.id, flake.id


async def test_import_fits_points_and_only_the_owner_sets_the_threshold(app, client):
    _run_id, flake_id = await _flake(app)
    await add_user(app, OWNER_EMAIL, OWNER_PASSWORD, role="owner")
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    await sign_in(client, OWNER_EMAIL, OWNER_PASSWORD)
    created = await client.post(
        "/api/calibration/batches", json={"flake_ids": [flake_id]}, headers=CSRF,
    )
    assert created.status_code == 201
    assert created.json()["item_count"] == 2
    csv = (
        "item_id,q1,q2\n"
        f"{flake_id},Yes,Real fix\n"
        f"{flake_id},Yes,Real fix\n"
        f"{flake_id},No,Hides it\n"
        "control-mismatch-1,Yes,Real fix\n"
    )
    imported = await client.post(
        "/api/calibration/import",
        content=csv.encode(),
        headers={**CSRF, "content-type": "text/csv"},
    )
    assert imported.status_code == 200
    assert imported.json()["control_accuracy"] == 0
    chart = await client.get("/api/calibration")
    assert chart.status_code == 200
    body = chart.json()
    assert body["partial"] is True
    assert body["source"] == "default"
    assert body["threshold"] == 0.8
    assert body["n_labels"] == 1
    assert body["points"]
    assert len(body["reliability"]) == 5
    assert "30 labels" in body["message"]
    await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    refused = await client.put(
        "/api/calibration/threshold", json={"threshold": 0.75, "reason": "member"}, headers=CSRF,
    )
    assert refused.status_code == 403
    refused_import = await client.post(
        "/api/calibration/import",
        content=csv.encode(),
        headers={**CSRF, "content-type": "text/csv"},
    )
    assert refused_import.status_code == 403
    await sign_in(client, OWNER_EMAIL, OWNER_PASSWORD)
    saved = await client.put(
        "/api/calibration/threshold",
        json={"threshold": 0.75, "reason": "Owner chose a stricter cutoff."},
        headers=CSRF,
    )
    assert saved.status_code == 200
    assert saved.json()["source"] == "manual"
    assert saved.json()["threshold"] == 0.75
    async with app.state.sessionmaker() as db:
        logged = await db.scalar(
            select(SecurityLog).where(SecurityLog.action == "calibration_threshold")
        )
        item = await db.scalar(select(AuditItem).where(AuditItem.flake_id == flake_id))
        route_threshold, source, _points = await _threshold(db, app.state.settings)
    assert logged is not None and logged.outcome == "success"
    assert item.consensus == "1"
    assert source == "manual"
    assert route_threshold == 0.75


def test_bad_csv_columns_are_rejected():
    from app.integrations.audit.csv_import import CsvError, parse_labels

    try:
        parse_labels(b"item_id,label\nabc,1\n")
    except CsvError as exc:
        assert "item_id, q1, q2" in str(exc)
    else:
        raise AssertionError("bad columns were accepted")
