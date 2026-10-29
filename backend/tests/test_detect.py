import pytest

from app.api.flakes import research_note
from app.services.detect import SuiteStartError, detect, summarise


def _it(index: int, results: dict[str, str], order: list[str] | None = None) -> dict:
    ids = order or list(results)
    return {
        "index": index, "seed": index, "hash_seed": index, "order": ids,
        "results": [
            {"test_id": t, "outcome": o, "duration_ms": 10,
             "traceback": None if o == "passed" else "boom"}
            for t, o in results.items()
        ],
    }


def test_summarise_separates_flaky_and_broken():
    iterations = [
        _it(i, {"flaky::t": "failed" if i < 6 else "passed", "broken::t": "failed",
                "ok::t": "passed"})
        for i in range(30)
    ]
    summary = summarise(iterations)
    assert summary["test_count"] == 3
    assert [f["test_id"] for f in summary["flakes"]] == ["flaky::t"]
    assert summary["flakes"][0]["fail_count"] == 6
    assert [b["test_id"] for b in summary["broken"]] == ["broken::t"]
    assert len(summary["flakes"][0]["failing_samples"]) == 3
    assert len(summary["flakes"][0]["passing_samples"]) == 3


def test_research_note_keeps_the_search_outcome():
    assert research_note([{"message": "5 upstream references"}]) is None
    assert research_note([{"message": "Search unavailable"}]) == "Search unavailable"
    found = "No upstream references found"
    assert research_note([{"message": found}]) == found


@pytest.mark.asyncio
async def test_collection_error_stops_detection():
    class Client:
        async def submit(self, body):
            return {"iterations": [{
                "status": "collection_error", "error": "No module named nope", "results": [],
            }]}

    with pytest.raises(SuiteStartError, match="No module named nope"):
        async for _ in detect(Client(), "flaky-shop", 4, 30, 2):
            pass
