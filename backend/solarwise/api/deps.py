"""Request-scoped dependencies."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from solarwise import security
from solarwise.api.errors import ApiError
from solarwise.config import Settings
from solarwise.db.models import Role, User

logger = logging.getLogger("solarwise.api")

#: Carries the same access token as ``Authorization: Bearer``.  Some reverse proxies and hosting gateways remove the
#: ``Authorization`` header, or replace it with a credential of their own, before a request reaches the application.
TOKEN_HEADER = "X-SolarWise-Token"  # noqa: S105 - the name of a header, not a secret

_bearer = HTTPBearer(auto_error=False, description="Access token returned by /api/v1/auth/login")
_token_header = APIKeyHeader(
    name=TOKEN_HEADER, auto_error=False, scheme_name="AccessTokenHeader",
    description="The same access token in a header of its own, for servers behind a proxy that removes or replaces "
                "the Authorization header.",
)


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Iterator[Session]:
    """One session per request: committed when the handler has succeeded, rolled back otherwise.

    Used with ``scope="function"`` (see ``DbSession``): the commit happens *before* the answer leaves.  A client acts
    on an answer at once - it uses the token it was given, it opens the page of what it has just created - so a
    success must never be announced for data that are not stored yet, or that could not be stored at all.
    """
    session: Session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db, scope="function")]
AppSettings = Annotated[Settings, Depends(get_settings)]


def client_address(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _refused(request: Request, reason: str, message: str) -> ApiError:
    """A 401.  The reason is logged for the operator - never the token - and the client gets ``message``."""
    logger.info("401 on %s %s: %s", request.method, request.url.path, reason)
    return ApiError(401, "NOT_AUTHENTICATED", message, headers={"WWW-Authenticate": "Bearer"})


def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    header_token: Annotated[str | None, Depends(_token_header)],
    db: DbSession,
    settings: AppSettings,
) -> User:
    candidates: list[tuple[str, str]] = []
    if credentials is not None and credentials.scheme.lower() == "bearer" and credentials.credentials.strip():
        candidates.append(("Authorization", credentials.credentials.strip()))
    if header_token is not None and header_token.strip():
        candidates.append((TOKEN_HEADER, header_token.strip()))
    if not candidates:
        raise _refused(request, "no access token was received", "authentication is required")

    user_id: int | None = None
    source = ""
    problems: list[str] = []
    for source, token in candidates:
        try:
            user_id = int(security.decode_access_token(settings, token)["sub"])
            break
        except (security.TokenError, KeyError, ValueError) as exc:
            problems.append(f"{source}: {type(exc.__cause__ or exc).__name__}")
    if user_id is None:
        raise _refused(
            request, f"access token not accepted ({'; '.join(problems)})", "the access token is invalid or has expired"
        )

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _refused(request, "unknown or deactivated account", "the account is not active")
    if user.is_demo and not settings.demo_mode:
        raise _refused(request, "demonstration account while the demonstration is off", "the demonstration is not enabled")

    if source == TOKEN_HEADER and not getattr(request.app.state, "token_header_noticed", False):
        # Said once: it tells the operator what the proxy in front of the server does.
        request.app.state.token_header_noticed = True
        logger.warning(
            "a request was authenticated with the %s header because its Authorization header was %s on arrival; "
            "a proxy in front of this server is probably removing or replacing that header",
            TOKEN_HEADER, "missing" if credentials is None else "not usable",
        )
    return user


def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != Role.ADMIN.value:
        raise ApiError(403, "FORBIDDEN", "administrator rights are required")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
