"""Password hashing, access tokens and sign-in throttling."""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from solarwise.config import Settings

ALGORITHM = "HS256"
TOKEN_ISSUER = "solarwise"  # noqa: S105 - a claim value, not a credential
MIN_PASSWORD_LENGTH = 12

_hasher = PasswordHasher()  # Argon2id with the library's current recommended parameters
#: Verified against when the account does not exist, so that timing does not reveal which emails are registered.
_DUMMY_HASH = _hasher.hash("solarwise-timing-equaliser")


class TokenError(Exception):
    """The token is missing, malformed, expired or not signed by this service."""


def password_problem(password: str) -> str | None:
    """Reason why ``password`` is not acceptable, or ``None``."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"the password must have at least {MIN_PASSWORD_LENGTH} characters"
    if len(password) > 256:
        return "the password is too long"
    if password.strip() != password:
        return "the password must not start or end with a space"
    if len(set(password)) < 5:
        return "the password is too repetitive"
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-effort verification: an absent hash is checked against a dummy one."""
    try:
        _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


#: Tolerance on the time claims of a token.  The clock of a server can be stepped (time synchronisation, a virtual
#: machine resumed from a snapshot): a token issued a moment before such a step must not be refused as "not yet valid".
CLOCK_LEEWAY = timedelta(seconds=30)


def create_access_token(settings: Settings, *, user_id: int, role: str, is_demo: bool) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "iss": TOKEN_ISSUER,
        "sub": str(user_id),
        "role": role,
        "demo": is_demo,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(payload, settings.signing_key, algorithm=ALGORITHM), expires


def decode_access_token(settings: Settings, token: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.signing_key,
            algorithms=[ALGORITHM],
            issuer=TOKEN_ISSUER,
            leeway=CLOCK_LEEWAY,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    return payload


class AttemptLimiter:
    """Sliding-window limiter of failed sign-ins per key (remote address + account).

    In-process: adequate for a single instance.  Behind several instances the
    per-account lockout stored in the database remains effective.
    """

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        events = self._events.setdefault(key, deque())
        while events and now - events[0] > self.window_seconds:
            events.popleft()
        return events

    def blocked_for(self, key: str) -> float:
        """Seconds until ``key`` may try again (0 when not blocked)."""
        now = time.monotonic()
        with self._lock:
            events = self._prune(key, now)
            if len(events) < self.max_attempts:
                if not events:
                    self._events.pop(key, None)
                return 0.0
            return max(0.0, self.window_seconds - (now - events[0]))

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(key, now).append(now)
            if len(self._events) > 50_000:  # bound memory under a distributed attack
                for stale in [k for k, v in self._events.items() if not v or now - v[-1] > self.window_seconds]:
                    self._events.pop(stale, None)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)
