"""Runtime configuration, read from the environment (and an optional ``.env`` file).

Nothing security-relevant has a usable default in production: the application
refuses to start there without a secret key.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PACKAGE_ROOT = Path(__file__).resolve().parent
#: ``frontend/dist`` of a source checkout (``backend/solarwise/config.py`` -> repository root).
DEFAULT_FRONTEND_DIST = PACKAGE_ROOT.parent.parent / "frontend" / "dist"

CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOLARWISE_", env_file=".env", extra="ignore")

    environment: Literal["development", "production", "test"] = "development"
    database_url: str = Field(
        default="sqlite:///./var/solarwise.db",
        validation_alias=AliasChoices("SOLARWISE_DATABASE_URL", "DATABASE_URL"),
    )
    #: Signing key of access tokens.  Mandatory in production.
    secret_key: str | None = None
    access_token_minutes: int = Field(default=60, ge=5, le=24 * 60)

    #: Demonstration mode: seeds the synthetic reference plant and enables password-less demo sign-in.
    demo_mode: bool = False

    #: Sign-up: whoever can reach the application may create an account for themselves.  Such an account gets the
    #: ENGINEER role - never ADMIN - and sees no plant of anybody else.  ``false`` leaves account creation to
    #: administrators and to the command line.
    allow_registration: bool = True

    #: Administrator created at start-up while the installation has none (production bootstrap).
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    # --- HTTP surface
    cors_origins: CsvList = Field(default_factory=list)
    allowed_hosts: CsvList = Field(default_factory=lambda: ["*"])
    #: Value of the CSP ``frame-ancestors`` directive ("'none'", "'self'", a list of origins, or "*").
    frame_ancestors: str = "'self'"
    frontend_dist: Path = DEFAULT_FRONTEND_DIST
    max_upload_mb: int = Field(default=25, ge=1, le=200)

    # --- sign-in throttling
    login_max_attempts: int = Field(default=5, ge=1, le=100)
    login_window_seconds: int = Field(default=300, ge=10, le=24 * 3600)
    login_lockout_seconds: int = Field(default=900, ge=10, le=24 * 3600)

    # --- external data services (never required)
    external_data_enabled: bool = True
    external_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    nasa_power_base_url: str = "https://power.larc.nasa.gov"
    pvgis_base_url: str = "https://re.jrc.ec.europa.eu"

    # --- optional language model used only to rephrase the engine's explanation
    ai_provider: Literal["none", "openai", "anthropic"] = "none"
    ai_api_key: str | None = None
    ai_base_url: str | None = None
    ai_model: str | None = None
    ai_timeout_seconds: float = Field(default=30.0, gt=0, le=180)

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def _split(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _check(self) -> Settings:
        if self.environment == "production":
            if not self.secret_key or len(self.secret_key) < 32:
                raise ValueError("SOLARWISE_SECRET_KEY (at least 32 characters) is required in production")
            if "*" in self.cors_origins:
                raise ValueError("SOLARWISE_CORS_ORIGINS must list explicit origins in production")
        if self.ai_provider != "none" and not self.ai_api_key:
            raise ValueError("SOLARWISE_AI_API_KEY is required when SOLARWISE_AI_PROVIDER is set")
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def signing_key(self) -> str:
        """The configured key, or a random one that lasts for this process only."""
        if self.secret_key:
            return self.secret_key
        return _ephemeral_key()

    @property
    def secret_key_is_ephemeral(self) -> bool:
        return not self.secret_key


@lru_cache(maxsize=1)
def _ephemeral_key() -> str:
    return secrets.token_urlsafe(48)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
