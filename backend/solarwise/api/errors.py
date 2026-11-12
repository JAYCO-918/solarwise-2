"""One error shape for every failure: ``{"error": {"code", "message", "details"}}``."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from solarwise.services.errors import ServiceError

logger = logging.getLogger("solarwise.api")

_CODES = {
    400: "BAD_REQUEST", 401: "NOT_AUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 415: "UNSUPPORTED_MEDIA_TYPE", 422: "INVALID", 429: "TOO_MANY_REQUESTS",
    503: "UNAVAILABLE",
}


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None,
                 headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in err.get("loc", ()) if p != "body"), "message": err.get("msg", "")}
            for err in exc.errors()
        ]
        return JSONResponse(error_body("INVALID", "the request is not valid", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _CODES.get(exc.status_code, "ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        return JSONResponse(error_body(code, message), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # The cause is logged, never returned: internals are not the client's business.
        logger.exception("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(error_body("INTERNAL_ERROR", "an unexpected error occurred"), status_code=500)
