"""Configuration: safe defaults, and refusal to start unsafely in production."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from solarwise.config import Settings


def build(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_defaults_are_conservative(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SOLARWISE_DEMO_MODE", "SOLARWISE_SECRET_KEY", "SOLARWISE_DATABASE_URL", "DATABASE_URL",
                 "SOLARWISE_FRAME_ANCESTORS", "SOLARWISE_AI_PROVIDER", "SOLARWISE_ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)
    settings = build()
    assert settings.demo_mode is False
    assert settings.ai_provider == "none"
    assert settings.frame_ancestors == "'self'"
    assert settings.cors_origins == []
    assert settings.is_sqlite


@pytest.mark.safety
def test_production_requires_a_secret_key() -> None:
    with pytest.raises(ValidationError, match="SOLARWISE_SECRET_KEY"):
        build(environment="production")
    with pytest.raises(ValidationError, match="SOLARWISE_SECRET_KEY"):
        build(environment="production", secret_key="too-short")
    assert build(environment="production", secret_key="x" * 32).secret_key_is_ephemeral is False


@pytest.mark.safety
def test_production_refuses_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="CORS"):
        build(environment="production", secret_key="x" * 32, cors_origins=["*"])


def test_an_ai_provider_needs_a_key() -> None:
    with pytest.raises(ValidationError, match="AI_API_KEY"):
        build(ai_provider="openai", ai_model="some-model")
    assert build(ai_provider="openai", ai_model="some-model", ai_api_key="k").ai_provider == "openai"


def test_lists_are_read_from_comma_separated_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLARWISE_CORS_ORIGINS", "https://a.example, https://b.example ,")
    monkeypatch.setenv("SOLARWISE_ALLOWED_HOSTS", "solar.example")
    settings = build()
    assert settings.cors_origins == ["https://a.example", "https://b.example"]
    assert settings.allowed_hosts == ["solar.example"]


def test_database_url_accepts_the_conventional_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOLARWISE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db/solarwise")
    settings = build()
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert not settings.is_sqlite
