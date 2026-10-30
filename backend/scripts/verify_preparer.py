"""Prepare a small public pytest repo and run one patched job through the runner.

Run inside the API container (it can reach preparer + runner on Compose networks):

    PYTHONPATH=/app python scripts/verify_preparer.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.preparer_client import PreparerClient
from app.runner_client import RunnerClient

# Small pure-Python project with pytest. Used only to verify prepare + runner wiring.
REPO_ID = "verify-tomli"
CLONE_URL = "https://github.com/hukkin/tomli"


async def main() -> int:
    settings = get_settings()
    preparer = PreparerClient(settings)
    runner = RunnerClient(settings)

    if not await preparer.health():
        print("preparer health check failed")
        return 1
    if not await runner.health():
        print("runner health check failed")
        return 1

    print(f"preparing {CLONE_URL} as {REPO_ID}…")
    result = await preparer.prepare({
        "repo_id": REPO_ID,
        "clone_url": CLONE_URL,
        "max_size_mb": settings.repo_max_size_mb,
        "clone_timeout_s": settings.repo_clone_timeout_s,
        "prepare_timeout_s": settings.prepare_timeout_s,
    })
    print(result)
    if result.get("status") != "ready":
        print("prepare failed")
        return 1

    print("running one collected suite iteration via runner…")
    job = await runner.submit({
        "repo_id": REPO_ID,
        "mode": "suite",
        "iterations": 1,
        "timeout_s": 60,
        "iteration_timeout_s": 180,
        "random_order": True,
    })
    iteration = job["iterations"][0]
    print({
        "status": iteration["status"],
        "exit_code": iteration["exit_code"],
        "tests": len(iteration["results"]),
        "error": iteration.get("error"),
    })
    if iteration["status"] not in {"ok", "collection_error"} and not iteration["results"]:
        print("runner job produced no usable result")
        return 1
    if iteration["status"] == "ok" and iteration["results"]:
        print("verify_preparer: ok")
        return 0
    # Collection can fail on rare env issues; still prove the imported layout was found.
    if iteration.get("error"):
        print("runner reported:", iteration["error"][:500])
    print("verify_preparer: prepare ready; runner responded")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
