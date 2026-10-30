from app.db.models import Flake, Repo, Run, utcnow
from app.services.events import append_event, empty_steps
from tests.conftest import CSRF, MEMBER_EMAIL, MEMBER_PASSWORD, add_user, sign_in


async def _repo(app, repo_id: str = "flaky-shop") -> Repo:
    async with app.state.sessionmaker() as db:
        repo = await db.get(Repo, repo_id)
        if repo is None:
            repo = Repo(id=repo_id, name=repo_id, description="demo", path=repo_id,
                        test_count=0, editable_paths=["shop/**"])
            db.add(repo)
            await db.commit()
        return repo


async def _run(app, repo_id: str, status: str = "running", **fields) -> Run:
    await _repo(app, repo_id)
    async with app.state.sessionmaker() as db:
        run = Run(repo_id=repo_id, status=status, config={"detect_reruns": 30},
                  steps=empty_steps(), **fields)
        db.add(run)
        await db.flush()
        await append_event(db, run, "run.status", {"status": status})
        await db.commit()
        await db.refresh(run)
        return run


async def test_duplicate_run_returns_409_with_existing_id(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    existing = await _run(app, "flaky-shop", status="running")
    r = await client.post("/api/repos/flaky-shop/runs", headers=CSRF, json={})
    assert r.status_code == 409
    error = r.json()["error"]
    assert error["code"] == "run_already_active"
    assert error["run_id"] == existing.id


async def test_unknown_repo_is_404(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    r = await client.post("/api/repos/not-listed/runs", headers=CSRF, json={})
    assert r.status_code == 404


async def test_list_repos_and_runs(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    run = await _run(app, "flaky-shop", status="completed", finished_at=utcnow())
    async with app.state.sessionmaker() as db:
        db.add(Flake(run_id=run.id, test_id="t::a", state="detected",
                     fail_count=6, run_count=30, rate=0.2, ci_low=0.1, ci_high=0.4))
        db.add(Flake(run_id=run.id, test_id="t::b", state="broken",
                     fail_count=30, run_count=30, rate=1.0, ci_low=0.88, ci_high=1.0))
        await db.commit()
    repos = (await client.get("/api/repos")).json()
    assert {r["id"] for r in repos} >= {"flaky-shop"}
    shop = next(r for r in repos if r["id"] == "flaky-shop")
    assert shop["source"] == "demo"
    assert shop["prepare_status"] == "ready"
    assert shop["is_private"] is False
    settings = (await client.get("/api/settings")).json()
    assert settings["github"] == {
        "import_enabled": True, "oauth_enabled": False, "connected": False,
    }
    listed = (await client.get("/api/runs")).json()
    assert listed["items"][0]["id"] == run.id
    assert listed["items"][0]["flake_count"] == 1
    assert listed["items"][0]["broken_count"] == 1
    flakes = (await client.get(f"/api/runs/{run.id}/flakes")).json()
    assert {f["state"] for f in flakes} == {"detected", "broken"}


async def test_sse_replays_from_last_event_id(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    run = await _run(app, "flaky-shop", status="completed", finished_at=utcnow())
    async with app.state.sessionmaker() as db:
        run = await db.get(Run, run.id)
        await append_event(db, run, "flake.detected", {"test_id": "t::a"})
        await append_event(db, run, "run.finished", {"status": "completed"})
        await db.commit()

    events = []
    async with client.stream("GET", f"/api/runs/{run.id}/events",
                             headers={"Last-Event-ID": "1"}) as response:
        async for line in response.aiter_lines():
            events.append(line)
            if "run.finished" in line:
                break
    joined = "\n".join(events)
    assert "event: flake.detected" in joined
    assert "event: run.finished" in joined
    assert "id: 2" in joined


async def test_cancel_is_idempotent(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    run = await _run(app, "flaky-shop", status="completed", finished_at=utcnow())
    first = await client.post(f"/api/runs/{run.id}/cancel", headers=CSRF)
    second = await client.post(f"/api/runs/{run.id}/cancel", headers=CSRF)
    assert first.status_code == second.status_code == 202


async def test_resume_refused_unless_interrupted(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    run = await _run(app, "flaky-shop", status="completed", finished_at=utcnow())
    r = await client.post(f"/api/runs/{run.id}/resume", headers=CSRF)
    assert r.status_code == 409
