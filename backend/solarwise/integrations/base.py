"""Shared HTTP plumbing of the external-data clients."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import httpx

USER_AGENT = "SolarWise-DZ/0.1 (photovoltaic performance analysis)"


class IntegrationFailure(StrEnum):
    #: Integrations are switched off by configuration.
    DISABLED = "DISABLED"
    #: The service could not be reached (no network, DNS failure, time-out, 5xx).
    UNAVAILABLE = "UNAVAILABLE"
    #: The service answered and refused the request (4xx).
    REJECTED = "REJECTED"
    #: The answer does not have the documented structure; it is not interpreted.
    UNEXPECTED_RESPONSE = "UNEXPECTED_RESPONSE"


class IntegrationError(Exception):
    def __init__(self, service: str, failure: IntegrationFailure, message: str) -> None:
        super().__init__(f"{service}: {message}")
        self.service = service
        self.failure = failure
        self.message = message


def get_json(
    client: httpx.Client, service: str, url: str, params: dict[str, Any], *, enabled: bool = True
) -> dict[str, Any]:
    """GET ``url`` and return the decoded JSON object, or raise :class:`IntegrationError`."""
    if not enabled:
        raise IntegrationError(service, IntegrationFailure.DISABLED, "external data services are disabled by configuration")
    try:
        response = client.get(url, params=params, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    except httpx.TimeoutException as exc:
        raise IntegrationError(service, IntegrationFailure.UNAVAILABLE, "the service did not answer in time") from exc
    except httpx.HTTPError as exc:
        raise IntegrationError(
            service, IntegrationFailure.UNAVAILABLE, f"the service could not be reached ({type(exc).__name__})"
        ) from exc
    if response.status_code >= 500:
        raise IntegrationError(service, IntegrationFailure.UNAVAILABLE, f"the service answered HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise IntegrationError(service, IntegrationFailure.UNEXPECTED_RESPONSE, "the answer is not JSON") from exc
    if response.status_code >= 400:
        detail = ""
        if isinstance(payload, dict):
            raw = payload.get("message") or payload.get("messages") or payload.get("detail") or ""
            detail = "; ".join(str(x) for x in raw) if isinstance(raw, list) else str(raw)
        raise IntegrationError(
            service, IntegrationFailure.REJECTED,
            f"the service refused the request (HTTP {response.status_code})" + (f": {detail[:300]}" if detail else ""),
        )
    if not isinstance(payload, dict):
        raise IntegrationError(service, IntegrationFailure.UNEXPECTED_RESPONSE, "the answer is not a JSON object")
    return payload
