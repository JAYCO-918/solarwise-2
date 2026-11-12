"""ASGI middleware: response security headers, ``HEAD`` requests and a hard limit on request bodies."""

from __future__ import annotations

import json
import logging

from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from solarwise.config import Settings

logger = logging.getLogger("solarwise.api")

_DOCS_PREFIX = "/api/docs"
#: The interactive API documentation loads its assets from a public CDN.
_DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; object-src 'none'; base-uri 'self'"
)


def content_security_policy(frame_ancestors: str) -> str:
    return (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
        f"frame-ancestors {frame_ancestors}"
    )


class SecurityHeadersMiddleware:
    """Adds the security headers to every response that has not set them itself."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        ancestors = settings.frame_ancestors.strip() or "'self'"
        self._common = {
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=(), geolocation=(), microphone=(), payment=()",
        }
        if settings.environment == "production":
            self._common["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # X-Frame-Options can only express 'none' and 'self'; anything else is left to the CSP directive.
        legacy = {"'none'": "DENY", "'self'": "SAMEORIGIN"}.get(ancestors)
        if legacy is not None:
            self._common["X-Frame-Options"] = legacy
        self._csp = content_security_policy(ancestors)
        self._docs_csp = f"{_DOCS_CSP}; frame-ancestors {ancestors}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                for name, value in self._common.items():
                    headers.setdefault(name, value)
                headers.setdefault(
                    "Content-Security-Policy", self._docs_csp if path.startswith(_DOCS_PREFIX) else self._csp
                )
                if path.startswith("/api/"):
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            # Last line of defence: the cause is logged, the client learns nothing about the internals,
            # and the answer still carries the security headers.
            logger.exception("unhandled error on %s %s", scope.get("method"), path)
            if started:
                raise
            body = json.dumps(
                {"error": {"code": "INTERNAL_ERROR", "message": "an unexpected error occurred", "details": None}}
            ).encode()
            await send_with_headers({
                "type": "http.response.start", "status": 500,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            })
            await send_with_headers({"type": "http.response.body", "body": body})


class HeadMiddleware:
    """Answers ``HEAD`` wherever ``GET`` is answered: the same status and headers, without the body.

    Availability checks, link previews and reverse proxies commonly probe a server with ``HEAD``.  Refusing it makes a
    running application look unavailable, and a server that answers ``GET`` is expected to answer ``HEAD`` as well.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "HEAD":
            await self.app(scope, receive, send)
            return

        async def send_without_body(message: Message) -> None:
            if message["type"] in ("http.response.body", "http.response.pathsend"):
                message = {"type": "http.response.body", "body": b"", "more_body": bool(message.get("more_body", False))}
            await send(message)

        # The server keeps the original scope: it logs the request as HEAD and frames the answer accordingly.
        await self.app({**scope, "method": "GET"}, receive, send_without_body)


class BodyLimitMiddleware:
    """Refuses request bodies above ``max_bytes`` - declared or streamed - before they are buffered or parsed."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    def _message(self) -> str:
        return f"the request body exceeds the {self.max_bytes // (1024 * 1024)} MB limit"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            body = json.dumps(
                {"error": {"code": "PAYLOAD_TOO_LARGE", "message": self._message(), "details": None}}
            ).encode()
            await send({
                "type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                            (b"connection", b"close")],
            })
            await send({"type": "http.response.body", "body": body})
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # An HTTPException so that the framework reports it as such instead of a parsing error.
                    raise HTTPException(status_code=413, detail=self._message())
            return message

        await self.app(scope, limited_receive, send)
