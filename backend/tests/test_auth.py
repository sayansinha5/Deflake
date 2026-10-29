import pytest

from tests.conftest import (
    CSRF,
    MEMBER_EMAIL,
    MEMBER_PASSWORD,
    OWNER_EMAIL,
    OWNER_PASSWORD,
    add_user,
    client_for,
    sign_in,
)


async def test_protected_route_requires_session(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


async def test_sign_in_success_sets_hardened_cookie(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    r = await sign_in(client, MEMBER_EMAIL.upper(), MEMBER_PASSWORD)
    assert r.status_code == 204
    cookie = r.headers["set-cookie"].lower()
    assert "deflake_session=" in cookie
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == MEMBER_EMAIL
    assert body["role"] == "member" and body["is_admin"] is False
    assert {"id", "full_name", "expires_at"} <= body.keys()


async def test_wrong_password_and_unknown_email_look_the_same(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    wrong = await sign_in(client, MEMBER_EMAIL, "not-the-password")
    unknown = await sign_in(client, "nobody@example.test", MEMBER_PASSWORD)
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert wrong.json()["error"]["message"] == "Email or password is incorrect."


async def test_ip_lockout_after_five_failed_attempts(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    for _ in range(5):
        r = await sign_in(client, MEMBER_EMAIL, "wrong-password")
        assert r.status_code == 401
    r = await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    assert r.status_code == 429
    error = r.json()["error"]
    assert error["code"] == "too_many_attempts"
    assert error["message"].startswith("Too many attempts. Try again in")
    assert error["retry_after_minutes"] == 15


async def test_successful_sign_ins_do_not_count_toward_lockout(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    for _ in range(6):
        assert (await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)).status_code == 204


async def test_account_lockout_after_ten_failures(app, client):
    from app.security.ratelimit import signin_failures

    user = await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    for i in range(10):
        if i % 4 == 0:
            signin_failures.reset()
        await sign_in(client, MEMBER_EMAIL, "wrong-password")
    signin_failures.reset()
    r = await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    assert r.status_code == 429
    async with app.state.sessionmaker() as db:
        from app.db.models import User

        assert (await db.get(User, user.id)).locked_until is not None


async def test_sign_out_revokes_token(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    token = client.cookies.get("deflake_session")
    r = await client.delete("/api/auth/session", headers=CSRF)
    assert r.status_code == 204

    async with client_for(app) as replay:
        replay.cookies.set("deflake_session", token, path="/api")
        assert (await replay.get("/api/auth/me")).status_code == 401


async def test_register_creates_member_and_signs_in(client):
    r = await client.post("/api/auth/register", headers=CSRF, json={
        "full_name": "Meera Rao", "email": "Meera@Example.test", "password": "Checkout-2026!",
    })
    assert r.status_code == 201
    assert r.json()["role"] == "member" and r.json()["email"] == "meera@example.test"
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_register_cannot_choose_role(client):
    r = await client.post("/api/auth/register", headers=CSRF, json={
        "full_name": "Eve", "email": "eve@example.test", "password": "Checkout-2026!",
        "role": "owner",
    })
    assert r.status_code == 422


@pytest.mark.parametrize("password", ["short", "password1", "qwertyuiop"])
async def test_register_rejects_weak_passwords(client, password):
    r = await client.post("/api/auth/register", headers=CSRF, json={
        "full_name": "Weak", "email": "weak@example.test", "password": password,
    })
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "weak_password"


async def test_register_duplicate_email_is_generic(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    r = await client.post("/api/auth/register", headers=CSRF, json={
        "full_name": "Dup", "email": MEMBER_EMAIL, "password": "Checkout-2026!",
    })
    assert r.status_code == 400
    assert r.json()["error"]["message"].startswith("We couldn't create an account")


async def test_register_closed(app_factory):
    app = await app_factory(signup_enabled=False)
    async with client_for(app) as c:
        r = await c.post("/api/auth/register", headers=CSRF, json={
            "full_name": "X", "email": "x@example.test", "password": "Checkout-2026!",
        })
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "signup_closed"


async def test_password_change_signs_out_other_sessions(app):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    async with client_for(app) as first, client_for(app) as second:
        await sign_in(first, MEMBER_EMAIL, MEMBER_PASSWORD)
        await sign_in(second, MEMBER_EMAIL, MEMBER_PASSWORD)
        r = await first.post("/api/auth/password", headers=CSRF, json={
            "current_password": MEMBER_PASSWORD, "new_password": "Brand-new-pass-2026",
        })
        assert r.status_code == 204
        assert (await first.get("/api/auth/me")).status_code == 200
        assert (await second.get("/api/auth/me")).status_code == 401
    async with client_for(app) as fresh:
        assert (await sign_in(fresh, MEMBER_EMAIL, "Brand-new-pass-2026")).status_code == 204


async def test_members_routes_are_owner_only(app):
    await add_user(app, OWNER_EMAIL, OWNER_PASSWORD, role="owner")
    member = await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)

    async with client_for(app) as as_member:
        await sign_in(as_member, MEMBER_EMAIL, MEMBER_PASSWORD)
        assert (await as_member.get("/api/members")).status_code == 403
        r = await as_member.post(f"/api/members/{member.id}/deactivate", headers=CSRF)
        assert r.status_code == 403

    async with client_for(app) as as_owner:
        await sign_in(as_owner, OWNER_EMAIL, OWNER_PASSWORD)
        listed = await as_owner.get("/api/members")
        assert listed.status_code == 200 and len(listed.json()) == 2
        r = await as_owner.post(f"/api/members/{member.id}/deactivate", headers=CSRF)
        assert r.status_code == 200 and r.json()["is_active"] is False

    async with client_for(app) as again:
        assert (await sign_in(again, MEMBER_EMAIL, MEMBER_PASSWORD)).status_code == 401


async def test_owner_cannot_deactivate_self(app):
    owner = await add_user(app, OWNER_EMAIL, OWNER_PASSWORD, role="owner")
    async with client_for(app) as c:
        await sign_in(c, OWNER_EMAIL, OWNER_PASSWORD)
        r = await c.post(f"/api/members/{owner.id}/deactivate", headers=CSRF)
    assert r.status_code == 400
