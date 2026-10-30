import pytest

from tests.conftest import CSRF, MEMBER_EMAIL, MEMBER_PASSWORD, add_user, sign_in


@pytest.mark.asyncio
async def test_defaults_update_is_returned_on_settings(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)

    before = await client.get("/api/settings")
    assert before.status_code == 200
    assert before.json()["defaults"]["detect_choices"] == [20, 30, 50]
    assert before.json()["defaults"]["verify_choices"] == [200, 400, 600]
    assert len(before.json()["models"]) == 3

    bad = await client.put(
        "/api/settings/defaults",
        headers=CSRF,
        json={"detect_reruns": 25, "verify_reruns": 200},
    )
    assert bad.status_code == 422

    updated = await client.put(
        "/api/settings/defaults",
        headers=CSRF,
        json={"detect_reruns": 50, "verify_reruns": 400},
    )
    assert updated.status_code == 200
    assert updated.json()["defaults"]["detect_reruns"] == 50
    assert updated.json()["defaults"]["verify_reruns"] == 400

    again = await client.get("/api/settings")
    assert again.json()["defaults"]["detect_reruns"] == 50
    assert again.json()["defaults"]["verify_reruns"] == 400
