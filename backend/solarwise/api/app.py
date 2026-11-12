"""Application factory."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.trustedhost import TrustedHostMiddleware

from solarwise import __version__
from solarwise.api import errors
from solarwise.api.deps import TOKEN_HEADER
from solarwise.api.middleware import BodyLimitMiddleware, HeadMiddleware, SecurityHeadersMiddleware
from solarwise.api.routes import advisory, analyses, auth, datasets, evidence, integrations, plants, reference
from solarwise.config import Settings, get_settings
from solarwise.db.base import build_engine, build_session_factory, session_scope
from solarwise.db.migrate import init_schema
from solarwise.security import AttemptLimiter
from solarwise.services import demo as demo_service
from solarwise.services import reference as reference_service
from solarwise.services import users as user_service
from solarwise.services.errors import ConflictError

logger = logging.getLogger("solarwise")

API_PREFIX = "/api/v1"

DESCRIPTION = """\
Photovoltaic performance intelligence and cleaning optimisation.

**How to read the results**

* The decision (`CLEAN_NOW`, `INVESTIGATE`, `MONITOR`) is produced by a deterministic rule engine. The rules and
  gates are published under `/api/v1/reference/decision-rules`.
* A production gap is an observation, not a diagnosis: on its own it never leads to `CLEAN_NOW`.
* Every value carries its provenance (`MEASURED`, `MODELLED`, `SYNTHETIC`, `UNKNOWN`). Synthetic, modelled and
  unknown-origin data never support an operational decision.
* Results for a demonstration plant, or obtained in a demonstration session, are marked `simulated` and are not
  operational instructions.
* A missing value means *not observed*. It is never read as zero and never interpolated.
"""

_NO_FRONTEND = """<!doctype html><html lang="en"><meta charset="utf-8"><title>SolarWise DZ</title>
<body style="font-family:system-ui,sans-serif;max-width:40rem;margin:4rem auto;line-height:1.5">
<h1>SolarWise DZ</h1>
<p>The API is running. The web interface has not been built on this server.</p>
<p>Build it with <code>npm ci &amp;&amp; npm run build</code> in <code>frontend/</code>, or use the
<a href="/api/docs">API documentation</a>.</p></body></html>"""


def _bootstrap_administrator(settings: Settings, db: Session) -> None:
    """The first administrator, from the bootstrap settings.  They are ignored once an administrator exists."""
    email, password = settings.bootstrap_admin_email, settings.bootstrap_admin_password
    if not (email and password):
        return
    try:
        created = user_service.bootstrap_administrator(db, email=email, password=password)
    except ConflictError:
        # Somebody signed up with that address before the administrator existed.  The server still starts: a
        # visitor must not be able to turn the next restart into an outage.
        logger.error(
            "no administrator was created: an account that is not an administrator already uses the address %s. "
            "Choose another SOLARWISE_BOOTSTRAP_ADMIN_EMAIL, or run 'solarwise create-user ADDRESS --role ADMIN' "
            "with another address; then deactivate that account if it is not yours.", email,
        )
        return
    if created is not None:
        logger.info("administrator account created for %s", email)


def _bootstrap(settings: Settings, session_factory: sessionmaker[Session]) -> None:
    """Reference entries, first administrator, demonstration content."""
    with session_scope(session_factory) as db:
        reference_service.sync_reference_values(db)
        _bootstrap_administrator(settings, db)
        if settings.demo_mode:
            created = demo_service.seed_demo(db)
            removed = user_service.purge_demo_sessions(db)
            logger.info("demonstration ready (%s created, %d expired sessions removed)", created, removed)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.schema_state = init_schema(engine)
        _bootstrap(settings, session_factory)
        if settings.secret_key_is_ephemeral:
            logger.warning("SOLARWISE_SECRET_KEY is not set: sessions end when this process stops")
        app.state.http_client = httpx.Client(timeout=settings.external_timeout_seconds, follow_redirects=False)
        try:
            yield
        finally:
            app.state.http_client.close()
            engine.dispose()

    app = FastAPI(
        title="SolarWise DZ API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.schema_state = "not initialised"
    app.state.login_limiter = AttemptLimiter(settings.login_max_attempts, settings.login_window_seconds)
    # Per address, across accounts: generous enough for an office behind one address.
    app.state.address_limiter = AttemptLimiter(settings.login_max_attempts * 6, settings.login_window_seconds)
    app.state.demo_limiter = AttemptLimiter(60, 300)
    # Sign-up attempts per address, refused ones included.  Enough for a room of people behind one address.
    app.state.registration_limiter = AttemptLimiter(20, 600)
    app.state.external_limiter = AttemptLimiter(20, 600)

    errors.install(app)

    # Added innermost first.  From the outside in, a request passes: HEAD handling (everything inside sees a GET),
    # security headers (so that every answer, including refusals and failures, carries them), host check, body
    # limit, CORS.
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type", TOKEN_HEADER],
            max_age=600,
        )
    # One megabyte of head-room for the multipart envelope around the largest allowed file.
    app.add_middleware(BodyLimitMiddleware, max_bytes=(settings.max_upload_mb + 1) * 1024 * 1024)
    if settings.allowed_hosts and "*" not in settings.allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    app.add_middleware(HeadMiddleware)

    api = APIRouter(prefix=API_PREFIX)
    #: (path pattern, methods) of every endpoint, to tell a wrong method from an unknown path.
    known_paths: list[tuple[re.Pattern[str], set[str]]] = []
    for module in (reference, auth, plants, datasets, evidence, analyses, integrations, advisory):
        api.include_router(module.router)
        known_paths.extend(
            (route.path_regex, set(route.methods or ())) for route in module.router.routes if isinstance(route, APIRoute)
        )
    app.include_router(api)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def _unknown_api(rest: str, request: Request) -> JSONResponse:
        """Unknown API paths answer in JSON - never with the web page - and wrong methods are named as such."""
        allowed: set[str] = set()
        version = API_PREFIX.removeprefix("/api/") + "/"
        if rest.startswith(version):
            sub_path = "/" + rest.removeprefix(version)
            for pattern, methods in known_paths:
                if pattern.match(sub_path):
                    allowed |= methods
        if "GET" in allowed:
            allowed.add("HEAD")
        if allowed:
            return JSONResponse(
                errors.error_body("METHOD_NOT_ALLOWED", f"{request.method} is not allowed on /api/{rest}"),
                status_code=405, headers={"Allow": ", ".join(sorted(allowed))},
            )
        return JSONResponse(errors.error_body("NOT_FOUND", f"no such API endpoint: /api/{rest}"), status_code=404)

    _mount_frontend(app, settings.frontend_dist)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built single-page application; unknown paths get ``index.html`` (client-side routing)."""
    dist = dist.resolve()
    index = dist / "index.html"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def _spa(path: str) -> Response:
        if not index.is_file():
            return HTMLResponse(_NO_FRONTEND)
        if path:
            candidate = (dist / path).resolve()
            # Only files inside the build directory, never anything reached through '..' or a symlink out of it.
            if candidate.is_relative_to(dist) and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def get_app() -> FastAPI:
    """Factory for ``uvicorn --factory solarwise.api.app:get_app``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
