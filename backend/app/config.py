from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_DEFAULTS: dict[str, str] = {
    "JWT_SECRET": "dev_only_jwt_secret_change_me_7f3a9c2e1b8d4f60",
    "RUNNER_SHARED_SECRET": "dev_only_runner_secret_change_me_4e91b07d",
    "PREPARER_SHARED_SECRET": "dev_only_preparer_secret_change_me_9c2d41aa",
    "DB_PASSWORD": "deflake_app_dev_pw",
    "DB_MIGRATION_PASSWORD": "deflake_migrator_dev_pw",
    "OWNER_PASSWORD": "Owner2026",
    "DEMO_ACCOUNT_PASSWORD": "Judge2026",
}

MIN_PRODUCTION_SECRET_LENGTH = 32


class ConfigError(ValueError):
    pass


def _choice(value: str | None, allowed: set[str], default: str, env_name: str) -> str:
    """First word of a provider setting. Ignores a trailing inline comment."""
    raw = value.split("#", 1)[0].strip() if isinstance(value, str) else ""
    token = raw.split()[0] if raw else ""
    if not token:
        return default
    if token not in allowed:
        raise ConfigError(f"{env_name} must be one of: {', '.join(sorted(allowed))}.")
    return token


def _token(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.split("#", 1)[0].strip()
    return raw.split()[0] if raw else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # App
    app_env: Literal["development", "production"] = "development"
    app_name: str = "Deflake"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    public_base_url: str = "http://localhost:5173"
    cors_allowed_origins: str = "http://localhost:5173"

    # Auth
    signup_enabled: bool = True
    password_min_length: int = 8
    owner_name: str = "Workspace Owner"
    owner_email: str
    owner_password: SecretStr
    jwt_secret: SecretStr
    jwt_ttl_minutes: int = 480
    cookie_secure: bool = False
    demo_account_email: str | None = None
    demo_account_password: SecretStr | None = None

    # Database
    db_host: str = "mysql"
    db_port: int = 3306
    db_name: str = "deflake"
    db_user: str
    db_password: SecretStr
    db_migration_user: str
    db_migration_password: SecretStr
    db_pool_size: int = 10
    db_pool_recycle_s: int = 280
    db_charset: str = "utf8mb4"

    # AI provider
    ai_provider: Literal[
        "nebius_token_factory", "nvidia_nim", "openai_compatible", "anthropic", "fake"
    ] = "nebius_token_factory"
    ai_base_url: str | None = None
    ai_api_key: SecretStr | None = None
    ai_model_fast: str | None = None
    ai_model_balanced: str | None = None
    ai_model_reasoning: str | None = None
    ai_structured_output_method: Literal["json_schema", "json_mode", "parse"] = "json_schema"
    ai_temperature_default: float = 0.2
    ai_temperature_self_consistency: float = 0.7
    ai_request_timeout_s: int = 90
    ai_max_retries: int = 3
    ai_price_fast_in_per_mtok: float | None = None
    ai_price_fast_out_per_mtok: float | None = None
    ai_price_balanced_in_per_mtok: float | None = None
    ai_price_balanced_out_per_mtok: float | None = None
    ai_price_reasoning_in_per_mtok: float | None = None
    ai_price_reasoning_out_per_mtok: float | None = None
    langsmith_tracing: bool = False
    langsmith_project: str = "deflake"
    self_consistency_samples: int = 3
    max_patch_attempts: int = 3
    confidence_threshold_default: float = 0.80
    calibration_min_labels: int = 30
    checkpoint_table_prefix: str = "lg_"

    # Tavily
    tavily_enabled: bool = True
    tavily_max_results: int = 5
    tavily_search_depth: Literal["basic", "advanced"] = "basic"

    # Integration keys (blank disables the integration)
    tavily_api_key: SecretStr | None = None
    tendem_api_key: SecretStr | None = None
    toloka_api_key: SecretStr | None = None
    langsmith_api_key: SecretStr | None = None
    github_token: SecretStr | None = None
    escalation_provider: str | None = "tendem"
    escalation_fallback: str | None = "local"
    tendem_mcp_url: str | None = None
    tendem_base_url: str | None = None
    github_repo: str | None = None
    audit_provider: str | None = "toloka"
    toloka_base_url: str | None = None
    toloka_pipeline_id: str | None = None
    toloka_env: str | None = "sandbox"
    toloka_overlap: int = 3

    # GitHub repository import (public URL and optional OAuth)
    github_import_enabled: bool = True
    github_public_token: SecretStr | None = None
    github_oauth_enabled: bool = False
    github_oauth_client_id: str | None = None
    github_oauth_client_secret: SecretStr | None = None
    github_oauth_redirect_uri: str = "http://localhost:8000/api/github/oauth/callback"
    github_oauth_scopes: str = "repo read:user"
    github_oauth_success_url: str = "http://localhost:5173/settings/integration"
    github_token_encryption_key: SecretStr | None = None
    preparer_url: str = "http://preparer:8200"
    preparer_shared_secret: SecretStr
    repo_max_size_mb: int = 200
    repo_clone_timeout_s: int = 120
    prepare_timeout_s: int = 600
    max_imported_repos_per_user: int = 10

    # Runner and run limits
    runner_url: str = "http://runner:8100"
    runner_shared_secret: SecretStr
    runner_batch_size: int = 4
    detect_reruns: int = 30
    verify_reruns: int = 200
    verify_reruns_max: int = 600
    per_test_run_timeout_s: int = 60
    run_time_budget_min: int = 25
    max_concurrent_runs: int = 2
    ai_run_budget_usd: float = 2.00
    allowlist_path: str = "../demo-repos/allowlist.yaml"
    log_max_chars: int = 8000

    @field_validator("toloka_overlap", mode="before")
    @classmethod
    def _overlap_token(cls, value):
        if value is None or isinstance(value, int):
            return 3 if value is None else value
        token = str(value).split("#", 1)[0].strip().split()
        return token[0] if token else 3

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_none(cls, value):
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origins(self) -> list[str]:
        raw = self.cors_allowed_origins.split("#", 1)[0]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @model_validator(mode="after")
    def _validate(self) -> "Settings":
        self.escalation_provider = _choice(
            self.escalation_provider, {"tendem", "github_issue", "local"},
            "tendem", "ESCALATION_PROVIDER",
        )
        self.escalation_fallback = _choice(
            self.escalation_fallback, {"github_issue", "local"},
            "local", "ESCALATION_FALLBACK",
        )
        self.audit_provider = _choice(
            self.audit_provider, {"toloka", "csv_import"}, "toloka", "AUDIT_PROVIDER",
        )
        self.toloka_env = _choice(
            self.toloka_env, {"sandbox", "production"}, "sandbox", "TOLOKA_ENV",
        )
        self.toloka_base_url = _token(self.toloka_base_url)
        self.toloka_pipeline_id = _token(self.toloka_pipeline_id)
        if not 1 <= self.toloka_overlap <= 10:
            raise ConfigError("TOLOKA_OVERLAP must be from 1 to 10.")
        if any(o == "*" or "*" in o for o in self.cors_origins):
            raise ConfigError("CORS_ALLOWED_ORIGINS must list exact origins, never a wildcard.")
        if not self.cors_origins:
            raise ConfigError("CORS_ALLOWED_ORIGINS is empty.")

        if self.ai_provider == "fake":
            if self.app_env != "development":
                raise ConfigError("AI_PROVIDER=fake is only allowed when APP_ENV=development.")
        else:
            for name in ("ai_base_url", "ai_api_key", "ai_model_fast", "ai_model_balanced",
                         "ai_model_reasoning"):
                if getattr(self, name) is None:
                    raise ConfigError(
                        f"{name.upper()} is required when AI_PROVIDER={self.ai_provider}."
                    )

        if self.github_oauth_enabled:
            if not self.github_oauth_client_id:
                raise ConfigError(
                    "GITHUB_OAUTH_CLIENT_ID is required when GITHUB_OAUTH_ENABLED=true."
                )
            if self.github_oauth_client_secret is None:
                raise ConfigError(
                    "GITHUB_OAUTH_CLIENT_SECRET is required when GITHUB_OAUTH_ENABLED=true."
                )
            if self.github_token_encryption_key is None:
                raise ConfigError(
                    "GITHUB_TOKEN_ENCRYPTION_KEY is required when GITHUB_OAUTH_ENABLED=true."
                )
            try:
                from cryptography.fernet import Fernet

                Fernet(self.github_token_encryption_key.get_secret_value().encode("utf-8"))
            except Exception as exc:
                raise ConfigError(
                    "GITHUB_TOKEN_ENCRYPTION_KEY must be a valid Fernet key "
                    "(generate with: make keys)."
                ) from exc

        if self.is_production:
            jwt = self.jwt_secret.get_secret_value()
            if len(jwt) < MIN_PRODUCTION_SECRET_LENGTH:
                raise ConfigError(
                    f"JWT_SECRET must be at least {MIN_PRODUCTION_SECRET_LENGTH} characters "
                    "in production."
                )
            for env_name, default in DEV_DEFAULTS.items():
                value = getattr(self, env_name.lower())
                if value is not None and value.get_secret_value() == default:
                    raise ConfigError(
                        f"{env_name} still has its development default; set a new value "
                        "for production."
                    )
        return self

    @property
    def database_url(self) -> str:
        return self._url("mysql+aiomysql", self.db_user, self.db_password, self.db_name)

    def migration_url(self, db_name: str | None = None) -> str:
        return self._url(
            "mysql+pymysql", self.db_migration_user, self.db_migration_password,
            db_name or self.db_name,
        )

    def _url(self, driver: str, user: str, password: SecretStr, db_name: str) -> str:
        from urllib.parse import quote_plus

        return (
            f"{driver}://{quote_plus(user)}:{quote_plus(password.get_secret_value())}"
            f"@{self.db_host}:{self.db_port}/{db_name}?charset={self.db_charset}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
