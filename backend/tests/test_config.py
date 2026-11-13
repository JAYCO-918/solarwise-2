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


def test_an_openai_compatible_service_on_ones_own_machines_may_take_no_key() -> None:
    own = build(ai_provider="openai-compatible", ai_model="m", ai_base_url="http://model-server.internal:8000/v1")
    assert own.ai_api_key is None and own.ai_enabled is True
    assert build(ai_provider="openai", ai_model="m", ai_base_url="http://127.0.0.1:11434/v1").ai_enabled is True
    # The public address of a commercial API is not "one's own machines", and Anthropic always takes a key.
    with pytest.raises(ValidationError, match="AI_API_KEY"):
        build(ai_provider="openai-compatible", ai_model="m")
    with pytest.raises(ValidationError, match="AI_API_KEY"):
        build(ai_provider="anthropic", ai_model="m", ai_base_url="https://proxy.example.org")


def test_the_language_model_is_on_only_with_a_provider_and_a_model() -> None:
    assert build().ai_enabled is False
    assert build(ai_provider="openai-compatible", ai_api_key="k").ai_enabled is False  # no model named
    assert build(ai_provider="none", ai_model="m", ai_api_key="k").ai_enabled is False
    assert build(ai_provider="anthropic", ai_model="m", ai_api_key="k").ai_enabled is True
    with pytest.raises(ValidationError):
        build(ai_provider="some-vendor", ai_model="m", ai_api_key="k")


def test_the_budget_of_a_model_call_is_bounded() -> None:
    settings = build()
    assert (settings.ai_max_output_tokens, settings.ai_max_retries, settings.ai_json_mode) == (2000, 1, False)
    assert settings.ai_timeout_seconds == 30.0
    for bad in ({"ai_max_output_tokens": 50}, {"ai_max_output_tokens": 100_000}, {"ai_max_retries": 10},
                {"ai_max_retries": -1}, {"ai_timeout_seconds": 0}, {"ai_timeout_seconds": 600}):
        with pytest.raises(ValidationError):
            build(**bad)


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
