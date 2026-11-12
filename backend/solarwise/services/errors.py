"""Errors raised by services; the API layer maps them to HTTP responses."""

from __future__ import annotations

from typing import Any


class ServiceError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details


class NotFoundError(ServiceError):
    status_code = 404
    code = "NOT_FOUND"


class ForbiddenError(ServiceError):
    status_code = 403
    code = "FORBIDDEN"


class ConflictError(ServiceError):
    status_code = 409
    code = "CONFLICT"


class InvalidError(ServiceError):
    status_code = 422
    code = "INVALID"


class UnavailableError(ServiceError):
    status_code = 503
    code = "UNAVAILABLE"
