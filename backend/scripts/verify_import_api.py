"""Live check of POST /api/repos/import against a small public repo.

Run inside the API container:

    PYTHONPATH=/app python scripts/verify_import_api.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = os.environ.get("VERIFY_BASE_URL", "http://127.0.0.1:8000")
EMAIL = os.environ.get("OWNER_EMAIL", "owner@deflake.local")
PASSWORD = os.environ.get("OWNER_PASSWORD", "Owner2026")
URL = "https://github.com/hukkin/tomli"
CSRF = {"X-Requested-With": "deflake"}


async def main() -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as client:
        login = await client.post(
            "/api/auth/session",
            headers=CSRF,
            json={"email": EMAIL, "password": PASSWORD},
        )
        if login.status_code not in {200, 204}:
            print("sign-in failed", login.status_code, login.text)
            return 1

        imported = await client.post(
            "/api/repos/import", headers=CSRF, json={"url": URL},
        )
        print("import", imported.status_code, imported.json())
        if imported.status_code != 200:
            return 1
        body = imported.json()
        repo_id = body["id"]

        for _ in range(60):
            await asyncio.sleep(5)
            detail = await client.get(f"/api/repos/{repo_id}", headers=CSRF)
            row = detail.json()
            status = row.get("prepare_status")
            print("status", status, "tests", row.get("test_count"), "err", row.get("prepare_error"))
            if status in {"ready", "failed"}:
                break
        else:
            print("timed out waiting for prepare")
            return 1

        if status != "ready":
            return 1

        # Duplicate should short-circuit.
        again = await client.post("/api/repos/import", headers=CSRF, json={"url": URL + ".git"})
        print("duplicate", again.status_code, again.json().get("already_imported"))
        if again.status_code != 200 or again.json().get("already_imported") is not True:
            return 1

        print("verify_import_api: ok")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
