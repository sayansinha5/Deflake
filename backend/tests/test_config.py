import pytest
from pydantic import ValidationError

from app.config import DEV_DEFAULTS, Settings

STRONG = "x" * 48

VALID = {
    "app_env": "development",
    "owner_email": "owner@example.test",
    "owner_password": "Owner-test-pass-2026",
    "jwt_secret": STRONG,
    "db_user": "app",
    "db_password": "app-pw",
    "db_migration_user": "migrator",
    "db_migration_password": "migrator-pw",
    "runner_shared_secret": STRONG,
    "ai_provider": "nebius_token_factory",
    "ai_base_url": "https://example.test/v1",
    "ai_api_key": "test-key",
    "ai_model_fast": "nano",
    "ai_model_balanced": "super",
    "ai_model_reasoning": "ultra",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def build(**overrides) -> Settings:
    return Settings(_env_file=None, **{**VALID, **overrides})


def test_valid_config_loads():
    settings = build()
    assert settings.cors_origins == ["http://localhost:5173"]


def test_cors_ignores_an_inline_comment():
    settings = build(
        cors_allowed_origins="http://localhost:5173 # comma-separated, no wildcards",
    )
    assert settings.cors_origins == ["http://localhost:5173"]


@pytest.mark.parametrize("missing", ["ai_api_key", "ai_base_url", "ai_model_reasoning"])
def test_refuses_missing_ai_values(missing):
    with pytest.raises(ValidationError, match=missing.upper()):
        build(**{missing: ""})


def test_refuses_missing_required_secret():
    values = {k: v for k, v in VALID.items() if k != "jwt_secret"}
    with pytest.raises(ValidationError, match="jwt_secret"):
        Settings(_env_file=None, **values)


@pytest.mark.parametrize("origins", ["*", "http://localhost:5173,*", "https://*.example.test"])
def test_refuses_wildcard_cors(origins):
    with pytest.raises(ValidationError, match="wildcard"):
        build(cors_allowed_origins=origins)


def test_refuses_short_jwt_secret_in_production():
    with pytest.raises(ValidationError, match="JWT_SECRET must be at least"):
        build(app_env="production", jwt_secret="short-secret")


@pytest.mark.parametrize("env_name", sorted(DEV_DEFAULTS))
def test_refuses_dev_defaults_in_production(env_name):
    with pytest.raises(ValidationError, match=env_name):
        build(app_env="production", **{env_name.lower(): DEV_DEFAULTS[env_name]})


def test_short_secret_allowed_in_development():
    assert build(jwt_secret="short").app_env == "development"


def test_fake_provider_refused_outside_development():
    with pytest.raises(ValidationError, match="AI_PROVIDER=fake"):
        build(app_env="production", ai_provider="fake")


def test_fake_provider_needs_no_ai_values():
    settings = build(ai_provider="fake", ai_api_key="", ai_base_url="")
    assert settings.ai_api_key is None


def test_blank_escalation_provider_uses_the_default():
    settings = build(escalation_provider="tendem # tendem | local", escalation_fallback="")
    assert settings.escalation_provider == "tendem"
    assert settings.escalation_fallback == "local"


def test_overlap_ignores_an_inline_comment():
    assert build(toloka_overlap="3 # reviewers per item").toloka_overlap == 3
    assert build(audit_provider="toloka # toloka | csv_import").audit_provider == "toloka"


def test_unknown_escalation_provider_is_rejected():
    with pytest.raises(ValidationError, match="ESCALATION_PROVIDER"):
        build(escalation_provider="slack")
