"""Access to the configured language model from the routes."""

from __future__ import annotations

from fastapi import Request

from solarwise.ai import Provider, build_provider
from solarwise.api.deps import client_address
from solarwise.config import Settings
from solarwise.db.models import User
from solarwise.security import AttemptLimiter


def provider_for(request: Request, settings: Settings, user: User) -> Provider | None:
    """The configured provider - or none for a demonstration visitor who has used up the allowance.

    The key never leaves this process: the provider object holds it, and nothing that is returned to a client,
    written to the audit trail or logged is derived from it.
    """
    provider = build_provider(settings, request.app.state.http_client)
    if provider is not None and user.is_demo:
        # Anonymous visitors must not be able to spend the operator's model budget without bound.
        limiter: AttemptLimiter = request.app.state.external_limiter
        key = f"ai|{client_address(request)}"
        if limiter.blocked_for(key) > 0:
            return None
        limiter.record_failure(key)
    return provider
