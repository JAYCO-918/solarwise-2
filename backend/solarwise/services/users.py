"""Accounts and sign-in."""

from __future__ import annotations

import re
import secrets
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from solarwise import security
from solarwise.config import Settings
from solarwise.db.base import utcnow
from solarwise.db.models import Analysis, Plant, Role, User
from solarwise.services.errors import ConflictError, ForbiddenError, InvalidError

DEMO_DOMAIN = "solarwise.invalid"  # RFC 2606 reserved domain: can never receive mail
#: A demonstration account, and everything created with it, is removed after this long.
DEMO_SESSION_LIFETIME = timedelta(hours=24)
#: Upper bound on demonstration accounts kept at any time (the oldest are removed first).
DEMO_SESSIONS_KEPT = 500
#: Role of an account created by its own user.  Never ADMIN: an administrator is made by another administrator, by
#: the command line or by the start-up bootstrap - all of which belong to whoever runs the server.
SELF_REGISTERED_ROLE = Role.ENGINEER
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s.]{2,}$")


def normalise_email(email: str) -> str:
    cleaned = email.strip().lower()
    if not _EMAIL.match(cleaned):
        raise InvalidError("not a valid e-mail address", code="INVALID_EMAIL")
    return cleaned


def count_administrators(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(User).where(User.role == Role.ADMIN.value)) or 0)


def bootstrap_administrator(db: Session, *, email: str, password: str) -> User | None:
    """Create the first administrator of an installation.  Returns it, or ``None`` when one exists already.

    The test is "no administrator", not "no account": with sign-up open, accounts can exist long before the first
    administrator.  An existing account that uses the address is never promoted - that would hand administrator
    rights to whoever holds its password, or a session of it that is still open: ``ConflictError`` instead.
    """
    if count_administrators(db) > 0:
        return None
    if get_by_email(db, email) is not None:
        raise ConflictError("an account that is not an administrator already uses this e-mail address",
                            code="EMAIL_TAKEN")
    return create_user(db, email=email, password=password, full_name="Administrator", role=Role.ADMIN)


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.strip().lower()))


def create_user(db: Session, *, email: str, password: str, full_name: str = "", role: Role = Role.VIEWER) -> User:
    email = normalise_email(email)
    problem = security.password_problem(password)
    if problem is not None:
        raise InvalidError(problem, code="WEAK_PASSWORD")
    if get_by_email(db, email) is not None:
        raise ConflictError("an account with this e-mail address already exists", code="EMAIL_TAKEN")
    user = User(email=email, full_name=full_name.strip(), role=role.value, password_hash=security.hash_password(password))
    db.add(user)
    db.flush()
    return user


def register_user(db: Session, *, email: str, password: str, full_name: str) -> User:
    """An account created by its own user (sign-up).

    The caller chooses an address, a name and a password - nothing else.  The role is fixed here, and the address is
    not verified: it identifies the account, it does not prove who its user is.
    """
    if normalise_email(email).endswith("@" + DEMO_DOMAIN):
        raise InvalidError("this e-mail domain is reserved for demonstration sessions", code="INVALID_EMAIL")
    user = create_user(db, email=email, password=password, full_name=full_name, role=SELF_REGISTERED_ROLE)
    user.last_login_at = utcnow()  # the account is signed in by the request that creates it
    return user


def create_demo_session(db: Session) -> User:
    """A fresh account for one visit of the public demonstration.

    Each visitor gets an account of their own, so that nothing one visitor does
    is visible to another.  The account has no password: it exists only behind
    the token issued by the demo sign-in, and is purged after a day.
    """
    user = User(
        email=f"demo-{secrets.token_hex(8)}@{DEMO_DOMAIN}", full_name="Demonstration visitor",
        role=Role.ENGINEER.value, password_hash=None, is_demo=True,
    )
    db.add(user)
    db.flush()
    return user


def purge_demo_sessions(db: Session, *, max_age: timedelta = DEMO_SESSION_LIFETIME, keep_at_most: int = DEMO_SESSIONS_KEPT) -> int:
    """Delete expired demonstration accounts with everything they created.  Returns how many were removed."""
    cutoff = utcnow() - max_age
    stale = list(db.scalars(select(User).where(User.is_demo.is_(True), User.created_at < cutoff)))
    stale_ids = {u.id for u in stale}
    live = [
        u for u in db.scalars(select(User).where(User.is_demo.is_(True)).order_by(User.created_at.desc(), User.id.desc()))
        if u.id not in stale_ids
    ]
    stale.extend(live[keep_at_most:])
    for user in stale:
        # Plants, with their datasets, evidence and analyses (database-level cascades).
        for plant in db.scalars(select(Plant).where(Plant.created_by_id == user.id)):
            db.delete(plant)
        db.flush()
        # Analyses the visitor ran on the shared demonstration plant.
        db.execute(delete(Analysis).where(Analysis.created_by_id == user.id))
        db.delete(user)
    db.flush()
    return len(stale)


def authenticate(db: Session, settings: Settings, *, email: str, password: str) -> User:
    """Verify credentials.  The same error is raised for every failure cause.

    Failed attempts are counted on the account; the caller commits the session
    whether the call succeeds or fails.
    """
    failure = ForbiddenError("e-mail address or password is incorrect", code="INVALID_CREDENTIALS")
    failure.status_code = 401
    user = get_by_email(db, email)
    now = utcnow()
    if user is not None and user.locked_until is not None and user.locked_until > now:
        security.verify_password(password, None)  # keep the response time comparable
        locked = ForbiddenError(
            "too many failed attempts; the account is temporarily locked", code="ACCOUNT_LOCKED"
        )
        locked.status_code = 429
        raise locked
    valid = security.verify_password(password, user.password_hash if user is not None else None)
    if user is None or not user.is_active or user.is_demo:
        raise failure
    if not valid:
        user.failed_logins += 1
        if user.failed_logins >= settings.login_max_attempts:
            user.locked_until = now + timedelta(seconds=settings.login_lockout_seconds)
            user.failed_logins = 0
        # The caller must commit before reporting the failure, or the counter would be lost.
        raise failure
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    assert user.password_hash is not None
    if security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(password)
    return user
