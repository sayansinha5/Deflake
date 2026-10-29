import json
from types import SimpleNamespace

from slowapi.errors import RateLimitExceeded
from starlette.requests import Request

from app.api.settings import _view
from app.errors import ApiError, _rate_limited
from app.security.passwords import hash_password, password_problem, verify_password
from tests.conftest import MEMBER_EMAIL, MEMBER_PASSWORD, add_user


async def test_state_changing_request_without_csrf_header_is_403(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    r = await client.post("/api/auth/session",
                          json={"email": MEMBER_EMAIL, "password": MEMBER_PASSWORD})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_header_missing"
    assert "set-cookie" not in r.headers


async def test_wrong_csrf_header_value_is_403(client):
    r = await client.delete("/api/auth/session", headers={"X-Requested-With": "XMLHttpRequest"})
    assert r.status_code == 403


async def test_security_headers_present(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "camera=()" in r.headers["permissions-policy"]
    assert r.headers["x-request-id"].startswith("req_")


async def test_error_shape_on_not_found(client):
    r = await client.get("/api/does-not-exist")
    assert r.status_code == 404
    error = r.json()["error"]
    assert set(error) >= {"code", "message", "request_id"}
    assert error["request_id"] == r.headers["x-request-id"]


async def test_validation_error_shape_has_no_input_echo(client):
    r = await client.post("/api/auth/session", headers={"X-Requested-With": "deflake"},
                          json={"email": "not-an-email", "password": "secret-value-123"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"
    assert "secret-value-123" not in r.text


async def test_unhandled_error_has_no_stack_trace(app, client):
    @app.get("/api/boom")
    async def boom():
        raise RuntimeError("internal detail that must not leak")

    r = await client.get("/api/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "internal detail" not in r.text and "Traceback" not in r.text


async def test_api_error_extra_fields(app, client):
    @app.get("/api/teapot")
    async def teapot():
        raise ApiError(409, "run_already_active", "A scan is already running.", {"run_id": "r1"})

    r = await client.get("/api/teapot")
    assert r.json()["error"]["run_id"] == "r1"


async def test_cors_allows_only_configured_origin(client):
    ok = await client.options("/api/auth/me", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    bad = await client.options("/api/auth/me", headers={
        "Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert ok.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in bad.headers


async def test_docs_disabled_in_production():
    from app.main import create_app
    from tests.conftest import client_for, make_settings

    settings = make_settings(
        app_env="production", ai_provider="nebius_token_factory",
        ai_base_url="https://example.test/v1", ai_api_key="k",
        ai_model_fast="a", ai_model_balanced="b", ai_model_reasoning="c",
        jwt_secret="p" * 48, runner_shared_secret="r" * 48,
        db_password="prod-app-pw", db_migration_password="prod-mig-pw",
        owner_password="Prod-owner-pw-1", demo_account_password=None,
    )
    app = create_app(settings)
    async with client_for(app) as c:
        assert (await c.get("/api/docs")).status_code == 404
        assert (await c.get("/api/openapi.json")).status_code == 404
    await app.state.engine.dispose()


async def test_docs_available_in_development(client):
    assert (await client.get("/api/docs")).status_code == 200


def test_password_hashing_round_trip():
    h = hash_password("Correct-horse-2026")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "Correct-horse-2026")
    assert not verify_password(h, "wrong")
    assert not verify_password(None, "anything")


def test_common_password_rejected():
    assert password_problem("iloveyou", 8) is not None
    assert password_problem("Correct-horse-2026", 8) is None


def _request(path: str) -> Request:
    return Request({
        "type": "http", "method": "POST", "path": path, "headers": [],
        "query_string": b"", "scheme": "http", "server": ("localhost", 80),
        "client": ("127.0.0.1", 9),
    })


def test_settings_view_reports_presence_not_secrets():
    settings = SimpleNamespace(
        ai_provider="fake", ai_api_key=None,
        ai_model_fast="nano", ai_model_balanced="super", ai_model_reasoning="ultra",
        detect_reruns=30, verify_reruns=200, confidence_threshold_default=0.8,
        ai_run_budget_usd=2, escalation_provider="tendem", escalation_fallback="local",
        tavily_api_key="tvly-secret-value-not-for-the-ui", tavily_enabled=True,
        tendem_api_key="tendem-secret-value-not-for-the-ui",
        toloka_api_key=None, audit_provider="csv_import",
    )
    dumped = json.dumps(_view(settings))
    assert "tvly-secret" not in dumped
    assert "tendem-secret" not in dumped
    statuses = {row["id"]: row["status"] for row in _view(settings)["integrations"]}
    assert statuses["tavily"] == "configured"
    assert statuses["tendem"] == "configured"
    assert statuses["ai"] == "disabled"


async def test_scan_limit_message_names_the_hour_cap():
    limit = SimpleNamespace(error_message=None, limit="10/hour")
    response = await _rate_limited(
        _request("/api/repos/flaky-shop/runs"), RateLimitExceeded(limit),
    )
    body = json.loads(response.body)
    assert body["error"]["code"] == "too_many_runs"
    assert "10 scans" in body["error"]["message"]
