from collections import defaultdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Evidence, Flake, TestOutcome
from app.runner_client import RunnerClient
from app.services.stats import wilson_interval

FAIL_OUTCOMES = {"failed", "error", "timeout"}
SAMPLE_WINDOW = 5
MAX_SAMPLES = 3
INSERT_BATCH = 500


class SuiteStartError(RuntimeError):
    """Pytest could not collect the suite. The message is the first error line."""


def classify_test(outcomes: list[str]) -> str | None:
    """Returns 'flaky', 'broken', or None (always passed / always skipped)."""
    counted = [o for o in outcomes if o != "skipped"]
    if not counted:
        return None
    fails = sum(1 for o in counted if o in FAIL_OUTCOMES)
    if fails == 0:
        return None
    return "broken" if fails == len(counted) else "flaky"


def _window(order: list[str], victim: str) -> list[str]:
    if victim not in order:
        return []
    i = order.index(victim)
    return order[max(0, i - SAMPLE_WINDOW): i + SAMPLE_WINDOW + 1]


def _samples(iterations: list[dict], test_id: str, want_fail: bool) -> list[dict]:
    out = []
    for it in iterations:
        by_id = {r["test_id"]: r for r in it["results"]}
        result = by_id.get(test_id)
        if result is None:
            continue
        failed = result["outcome"] in FAIL_OUTCOMES
        if failed != want_fail:
            continue
        out.append({
            "iteration": it["index"],
            "seed": it["seed"],
            "hash_seed": it["hash_seed"],
            "outcome": result["outcome"],
            "duration_ms": result["duration_ms"],
            "traceback": result.get("traceback"),
            "order_window": _window(it.get("order") or [r["test_id"] for r in it["results"]],
                                    test_id),
        })
        if len(out) >= MAX_SAMPLES:
            break
    return out


def summarise(iterations: list[dict]) -> dict[str, Any]:
    by_test: dict[str, list[str]] = defaultdict(list)
    for it in iterations:
        for result in it["results"]:
            by_test[result["test_id"]].append(result["outcome"])
    flakes, broken = [], []
    for test_id, outcomes in by_test.items():
        kind = classify_test(outcomes)
        if kind is None:
            continue
        n = sum(1 for o in outcomes if o != "skipped")
        fails = sum(1 for o in outcomes if o in FAIL_OUTCOMES)
        low, high = wilson_interval(fails, n)
        row = {
            "test_id": test_id, "fail_count": fails, "run_count": n,
            "rate": fails / n, "ci_low": low, "ci_high": high,
            "failing_samples": _samples(iterations, test_id, True),
            "passing_samples": _samples(iterations, test_id, False),
        }
        (broken if kind == "broken" else flakes).append(row)
    return {"flakes": flakes, "broken": broken, "test_count": len(by_test)}


async def store_outcomes(session: AsyncSession, run_id: str, iterations: list[dict],
                         phase: str = "detect") -> None:
    rows = []
    for it in iterations:
        seed, hash_seed = it["seed"], it["hash_seed"]
        for position, result in enumerate(it["results"]):
            rows.append(TestOutcome(
                run_id=run_id, phase=phase, iteration=it["index"], test_id=result["test_id"],
                outcome=result["outcome"], duration_ms=result["duration_ms"],
                seed=seed, hash_seed=hash_seed, position=position,
            ))
            if len(rows) >= INSERT_BATCH:
                session.add_all(rows)
                await session.flush()
                rows = []
    if rows:
        session.add_all(rows)
        await session.flush()


async def store_findings(session: AsyncSession, run_id: str, summary: dict) -> list[Flake]:
    stored: list[Flake] = []
    for kind, rows in (("flaky", summary["flakes"]), ("broken", summary["broken"])):
        for row in rows:
            flake = Flake(
                run_id=run_id, test_id=row["test_id"],
                state="broken" if kind == "broken" else "detected",
                fail_count=row["fail_count"], run_count=row["run_count"],
                rate=row["rate"], ci_low=row["ci_low"], ci_high=row["ci_high"],
            )
            session.add(flake)
            await session.flush()
            session.add(Evidence(
                flake_id=flake.id,
                failing_samples=row["failing_samples"],
                passing_samples=row["passing_samples"],
            ))
            stored.append(flake)
    return stored


async def detect(client: RunnerClient, repo_id: str, reruns: int, timeout_s: int,
                 batch_size: int) -> dict:
    """Runs the suite in batches so progress can be reported after each batch."""
    iterations: list[dict] = []
    remaining = reruns
    while remaining:
        n = min(batch_size, remaining)
        result = await client.submit({
            "repo_id": repo_id, "iterations": n, "timeout_s": timeout_s, "random_order": True,
        })
        for it in result["iterations"]:
            if it.get("status") == "collection_error":
                lines = (it.get("error") or "pytest could not collect tests").splitlines()
                first = lines[0][:300] if lines else "pytest could not collect tests"
                raise SuiteStartError(first)
            it["index"] = len(iterations)
            iterations.append(it)
        remaining -= n
        yield {"done": len(iterations), "total": reruns, "iterations": iterations[-n:]}
    yield {"done": reruns, "total": reruns, "summary": summarise(iterations)}
