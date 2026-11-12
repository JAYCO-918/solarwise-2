"""Sign-in and accounts."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from solarwise import security
from solarwise.api.deps import AdminUser, AppSettings, CurrentUser, DbSession, client_address
from solarwise.api.errors import ApiError
from solarwise.api.schemas import LoginRequest, RegisterRequest, TokenOut, UserCreate, UserOut, UserUpdate
from solarwise.db.models import Role, User
from solarwise.services import audit
from solarwise.services import demo as demo_service
from solarwise.services import users as user_service
from solarwise.services.errors import NotFoundError, ServiceError

router = APIRouter(tags=["accounts"])


def _token(settings: AppSettings, user: User) -> TokenOut:
    token, expires = security.create_access_token(settings, user_id=user.id, role=user.role, is_demo=user.is_demo)
    return TokenOut(access_token=token, expires_at=expires, user=UserOut.of(user))


@router.post("/auth/login", response_model=TokenOut, summary="Sign in with e-mail address and password")
def login(body: LoginRequest, request: Request, db: DbSession, settings: AppSettings) -> TokenOut:
    limiter: security.AttemptLimiter = request.app.state.login_limiter
    address_limiter: security.AttemptLimiter = request.app.state.address_limiter
    address = client_address(request)
    key = f"{address}|{body.email.strip().lower()[:254]}"
    wait = max(limiter.blocked_for(key), address_limiter.blocked_for(address))
    if wait > 0:
        raise ApiError(429, "TOO_MANY_ATTEMPTS", "too many failed sign-in attempts; try again later",
                       headers={"Retry-After": str(int(wait) + 1)})
    try:
        user = user_service.authenticate(db, settings, email=body.email, password=body.password)
    except ServiceError as exc:
        limiter.record_failure(key)
        address_limiter.record_failure(address)
        audit.record(db, "LOGIN_FAILED", detail={"email": body.email.strip().lower()[:254]}, remote_address=address)
        db.commit()
        raise ApiError(exc.status_code, exc.code, exc.message) from exc
    limiter.reset(key)
    audit.record(db, "LOGIN", user=user, remote_address=address)
    return _token(settings, user)


@router.post(
    "/auth/register", response_model=TokenOut, status_code=201, summary="Create an account for yourself (sign-up)",
    description="Creates an account and signs it in. The account gets the ENGINEER role: it can register plants and "
                "work on them, and it sees no plant of another account unless an owner shares one with it. It is "
                "never an administrator, and the request cannot name a role. The e-mail address is not verified. "
                "Available only while the server allows sign-up: see `registration_open` in `/api/v1/meta`.",
)
def register(body: RegisterRequest, request: Request, db: DbSession, settings: AppSettings) -> TokenOut:
    if not settings.allow_registration:
        raise ApiError(403, "REGISTRATION_CLOSED",
                       "sign-up is switched off on this server; an administrator creates the accounts")
    limiter: security.AttemptLimiter = request.app.state.registration_limiter
    address = client_address(request)
    wait = limiter.blocked_for(address)
    if wait > 0:
        raise ApiError(429, "TOO_MANY_REQUESTS", "too many accounts were requested from this address; try again later",
                       headers={"Retry-After": str(int(wait) + 1)})
    # Every attempt counts, refused ones included: the answer "this address is already registered" must not become
    # a way to test addresses without limit.
    limiter.record_failure(address)
    user = user_service.register_user(db, email=body.email, password=body.password, full_name=body.full_name)
    audit.record(db, "USER_REGISTERED", user=user, entity="user", entity_id=user.id, remote_address=address)
    return _token(settings, user)


@router.post(
    "/auth/demo-login", response_model=TokenOut, summary="Enter the demonstration (demo mode only)",
    description="Creates a temporary account for this visit. It can read the shared demonstration plant, run analyses "
                "that only it can see, and register its own demonstration plants. It is deleted after 24 hours.",
)
def demo_login(request: Request, db: DbSession, settings: AppSettings) -> TokenOut:
    if not settings.demo_mode:
        raise ApiError(404, "NOT_FOUND", "the demonstration is not enabled on this server")
    limiter: security.AttemptLimiter = request.app.state.demo_limiter
    address = client_address(request)
    wait = limiter.blocked_for(address)
    if wait > 0:
        raise ApiError(429, "TOO_MANY_REQUESTS", "too many demonstration sessions were opened; try again later",
                       headers={"Retry-After": str(int(wait) + 1)})
    limiter.record_failure(address)
    user_service.purge_demo_sessions(db)
    user = user_service.create_demo_session(db)
    demo_service.grant_demo_access(db, user)
    audit.record(db, "DEMO_LOGIN", user=user, remote_address=address)
    return _token(settings, user)


@router.get("/auth/me", response_model=UserOut, summary="The signed-in account")
def me(user: CurrentUser) -> UserOut:
    return UserOut.of(user)


@router.get("/users", response_model=list[UserOut], summary="List accounts (administrators)")
def list_users(_: AdminUser, db: DbSession) -> list[UserOut]:
    return [UserOut.of(u) for u in db.scalars(select(User).order_by(User.email))]


@router.post("/users", response_model=UserOut, status_code=201, summary="Create an account (administrators)")
def create_user(body: UserCreate, admin: AdminUser, db: DbSession, request: Request) -> UserOut:
    user = user_service.create_user(
        db, email=body.email, password=body.password, full_name=body.full_name, role=Role(body.role)
    )
    audit.record(db, "USER_CREATED", user=admin, entity="user", entity_id=user.id, remote_address=client_address(request))
    return UserOut.of(user)


@router.patch("/users/{user_id}", response_model=UserOut, summary="Change an account (administrators)")
def update_user(user_id: int, body: UserUpdate, admin: AdminUser, db: DbSession, request: Request) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("account not found")
    if user.id == admin.id and (body.is_active is False or (body.role is not None and body.role != Role.ADMIN.value)):
        raise ApiError(409, "CONFLICT", "an administrator cannot deactivate or demote their own account")
    if user.is_demo and body.role is not None:
        raise ApiError(409, "CONFLICT", "the role of the demonstration account cannot be changed")
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.role is not None:
        user.role = body.role
    if body.full_name is not None:
        user.full_name = body.full_name.strip()
    audit.record(db, "USER_UPDATED", user=admin, entity="user", entity_id=user.id,
                 detail=body.model_dump(exclude_none=True), remote_address=client_address(request))
    return UserOut.of(user)
