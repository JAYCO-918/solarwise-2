"""Language-model providers, reached over plain HTTPS (no vendor SDK)."""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from solarwise.config import Settings

MAX_OUTPUT_TOKENS = 700


class ProviderError(Exception):
    """The provider could not produce an answer (network, authentication, malformed reply)."""


class Provider(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str) -> str: ...


def _post(client: httpx.Client, url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    try:
        response = client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise ProviderError(f"the language-model provider could not be reached ({type(exc).__name__})") from exc
    if response.status_code >= 400:
        # The body may echo the request; only the status is reported.
        raise ProviderError(f"the language-model provider answered HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderError("the language-model provider did not answer with JSON") from exc
    if not isinstance(payload, dict):
        raise ProviderError("the language-model provider answered with an unexpected structure")
    return payload


class OpenAICompatibleProvider:
    """Any service implementing the ``/chat/completions`` interface."""

    name = "openai-compatible"

    def __init__(self, client: httpx.Client, *, base_url: str, api_key: str, model: str) -> None:
        self._client = client
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self.model = model

    def complete(self, system: str, user: str) -> str:
        payload = _post(
            self._client, self._url, {"Authorization": f"Bearer {self._key}"},
            {
                "model": self.model,
                "temperature": 0,
                "max_tokens": MAX_OUTPUT_TOKENS,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            },
        )
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("the language-model answer has no 'choices[0].message.content'") from exc
        if not isinstance(content, str):
            raise ProviderError("the language-model answer is not text")
        return content


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client: httpx.Client, *, base_url: str, api_key: str, model: str) -> None:
        self._client = client
        self._url = base_url.rstrip("/") + "/v1/messages"
        self._key = api_key
        self.model = model

    def complete(self, system: str, user: str) -> str:
        payload = _post(
            self._client, self._url, {"x-api-key": self._key, "anthropic-version": "2023-06-01"},
            {
                "model": self.model,
                "max_tokens": MAX_OUTPUT_TOKENS,
                "temperature": 0,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        blocks = payload.get("content")
        if not isinstance(blocks, list):
            raise ProviderError("the language-model answer has no 'content' list")
        text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
        if not text:
            raise ProviderError("the language-model answer contains no text")
        return text


def build_provider(settings: Settings, client: httpx.Client | None = None) -> Provider | None:
    """The configured provider, or ``None`` when the feature is switched off."""
    if settings.ai_provider == "none" or not settings.ai_api_key or not settings.ai_model:
        return None
    http = client or httpx.Client(timeout=settings.ai_timeout_seconds)
    if settings.ai_provider == "openai":
        return OpenAICompatibleProvider(
            http, base_url=settings.ai_base_url or "https://api.openai.com/v1",
            api_key=settings.ai_api_key, model=settings.ai_model,
        )
    return AnthropicProvider(
        http, base_url=settings.ai_base_url or "https://api.anthropic.com",
        api_key=settings.ai_api_key, model=settings.ai_model,
    )
