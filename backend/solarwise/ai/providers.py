"""Language-model providers, reached over plain HTTPS (no vendor SDK).

Two protocols are spoken: the OpenAI ``/chat/completions`` interface, which most
commercial services, gateways and self-hosted model servers implement, and the
Anthropic ``/v1/messages`` interface.  Changing provider is a matter of
configuration.

Whatever goes wrong - no answer in time, a refused key, a rate limit, a reply
that is not what the protocol promises - ends in a :class:`ProviderError` whose
text can be shown to a user: it never contains the key, the request or the body
of the provider's answer.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

import httpx

from solarwise.config import Settings

#: Kept for callers that size their own prompts; the budget in use is ``Settings.ai_max_output_tokens``.
MAX_OUTPUT_TOKENS = 700
#: Longest pause before another attempt, whatever the provider asks for [s].
MAX_RETRY_WAIT_SECONDS = 4.0
_RETRIED_STATUS = frozenset({429, 502, 503, 504})


class ProviderError(Exception):
    """The provider could not produce an answer.

    ``kind`` is one of ``TIMEOUT``, ``UNREACHABLE``, ``RATE_LIMITED``, ``REFUSED`` (credentials), ``HTTP_ERROR`` and
    ``MALFORMED``.
    """

    def __init__(self, message: str, kind: str = "MALFORMED") -> None:
        super().__init__(message)
        self.kind = kind


class Provider(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str) -> str: ...


def _retry_wait(response: httpx.Response | None, attempt: int) -> float:
    """Seconds to wait before attempt ``attempt + 1``: what the provider asks for, within bounds."""
    asked: float | None = None
    if response is not None:
        try:
            asked = float(response.headers.get("retry-after", ""))
        except ValueError:
            asked = None
    wait = asked if asked is not None and asked >= 0 else 0.5 * (attempt + 1)
    return min(wait, MAX_RETRY_WAIT_SECONDS)


def _post(
    client: httpx.Client, url: str, headers: dict[str, str], body: dict[str, Any], *,
    timeout: float | None = None, retries: int = 0, sleep: Any = time.sleep,
) -> dict[str, Any]:
    response: httpx.Response | None = None
    for attempt in range(retries + 1):
        last = attempt == retries
        try:
            if timeout is None:
                response = client.post(url, headers=headers, json=body)
            else:
                response = client.post(url, headers=headers, json=body, timeout=timeout)
        except httpx.TimeoutException as exc:
            # Not attempted again: the user has already waited for the whole time limit.
            raise ProviderError(
                "the language-model provider did not answer within the time limit", kind="TIMEOUT"
            ) from exc
        except httpx.HTTPError as exc:
            if last:
                raise ProviderError(
                    f"the language-model provider could not be reached ({type(exc).__name__})", kind="UNREACHABLE"
                ) from exc
            sleep(_retry_wait(None, attempt))
            continue
        if response.status_code in _RETRIED_STATUS and not last:
            sleep(_retry_wait(response, attempt))
            continue
        break
    assert response is not None
    status = response.status_code
    if status == 429:
        raise ProviderError(
            "the language-model provider refused the request: its rate limit or quota is reached (HTTP 429)",
            kind="RATE_LIMITED",
        )
    if status in (401, 403):
        raise ProviderError(
            f"the language-model provider refused the credentials (HTTP {status}): check the key and the model name",
            kind="REFUSED",
        )
    if status >= 400:
        # The body may echo the request; only the status is reported.
        raise ProviderError(f"the language-model provider answered HTTP {status}", kind="HTTP_ERROR")
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

    def __init__(
        self, client: httpx.Client, *, base_url: str, api_key: str | None, model: str,
        max_output_tokens: int = MAX_OUTPUT_TOKENS, timeout: float | None = None, retries: int = 0,
        json_mode: bool = False,
    ) -> None:
        self._client = client
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self.model = model
        self._max_tokens = max_output_tokens
        self._timeout = timeout
        self._retries = retries
        self._json_mode = json_mode

    def complete(self, system: str, user: str) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self._json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        payload = _post(self._client, self._url, headers, body, timeout=self._timeout, retries=self._retries)
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("the language-model answer has no 'choices[0].message.content'") from exc
        if not isinstance(content, str):
            raise ProviderError("the language-model answer is not text")
        return content


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self, client: httpx.Client, *, base_url: str, api_key: str, model: str,
        max_output_tokens: int = MAX_OUTPUT_TOKENS, timeout: float | None = None, retries: int = 0,
    ) -> None:
        self._client = client
        self._url = base_url.rstrip("/") + "/v1/messages"
        self._key = api_key
        self.model = model
        self._max_tokens = max_output_tokens
        self._timeout = timeout
        self._retries = retries

    def complete(self, system: str, user: str) -> str:
        payload = _post(
            self._client, self._url, {"x-api-key": self._key, "anthropic-version": "2023-06-01"},
            {
                "model": self.model,
                "max_tokens": self._max_tokens,
                "temperature": 0,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=self._timeout, retries=self._retries,
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
    if not settings.ai_enabled or not settings.ai_model:
        return None
    if not settings.ai_api_key and not (settings.ai_provider != "anthropic" and settings.ai_base_url):
        return None
    http = client or httpx.Client(timeout=settings.ai_timeout_seconds)
    common: dict[str, Any] = {
        "max_output_tokens": settings.ai_max_output_tokens, "timeout": settings.ai_timeout_seconds,
        "retries": settings.ai_max_retries,
    }
    if settings.ai_provider in ("openai", "openai-compatible"):
        return OpenAICompatibleProvider(
            http, base_url=settings.ai_base_url or "https://api.openai.com/v1",
            api_key=settings.ai_api_key, model=settings.ai_model, json_mode=settings.ai_json_mode, **common,
        )
    assert settings.ai_api_key is not None
    return AnthropicProvider(
        http, base_url=settings.ai_base_url or "https://api.anthropic.com",
        api_key=settings.ai_api_key, model=settings.ai_model, **common,
    )
