"""Passwords, access tokens and sign-in throttling."""

from __future__ import annotations

import base64
import json
import time

import jwt
import pytest

from solarwise import security
from tests.conftest import make_settings

pytestmark = pytest.mark.safety


def test_password_hash_is_argon2id_and_verifies() -> None:
    hashed = security.hash_password("a long and unusual passphrase")
    assert hashed.startswith("$argon2id$")
    assert "passphrase" not in hashed
    assert security.verify_password("a long and unusual passphrase", hashed)
    assert not security.verify_password("a long and unusual passphrasE", hashed)


def test_two_hashes_of_the_same_password_differ() -> None:
    assert security.hash_password("a long and unusual passphrase") != security.hash_password("a long and unusual passphrase")


def test_verification_without_a_stored_hash_fails_but_still_does_the_work() -> None:
    # An unknown account is verified against a dummy hash so that timing does not reveal its absence.
    assert security.verify_password("anything at all", None) is False


def test_a_corrupt_stored_hash_never_verifies() -> None:
    assert security.verify_password("anything at all", "not-a-hash") is False


@pytest.mark.parametrize(
    ("password", "fragment"),
    [
        ("short", "at least"),
        ("aaaaaaaaaaaaaaaa", "repetitive"),
        (" leading space is here", "space"),
        ("x" * 300, "too long"),
    ],
)
def test_weak_passwords_are_refused_with_a_reason(password: str, fragment: str) -> None:
    problem = security.password_problem(password)
    assert problem is not None and fragment in problem


def test_an_acceptable_password_has_no_problem() -> None:
    assert security.password_problem("correct horse battery staple") is None


def test_token_round_trip_carries_the_claims() -> None:
    settings = make_settings()
    token, expires = security.create_access_token(settings, user_id=42, role="ENGINEER", is_demo=False)
    payload = security.decode_access_token(settings, token)
    assert payload["sub"] == "42"
    assert payload["role"] == "ENGINEER"
    assert payload["demo"] is False
    assert payload["exp"] == int(expires.timestamp())


def test_token_signed_with_another_key_is_refused() -> None:
    token, _ = security.create_access_token(make_settings(secret_key="k" * 48), user_id=1, role="ADMIN", is_demo=False)
    with pytest.raises(security.TokenError):
        security.decode_access_token(make_settings(secret_key="z" * 48), token)


def test_expired_token_is_refused() -> None:
    settings = make_settings()
    now = int(time.time())
    token = jwt.encode(
        {"iss": security.TOKEN_ISSUER, "sub": "1", "iat": now - 7200, "exp": now - 3600},
        settings.signing_key, algorithm=security.ALGORITHM,
    )
    with pytest.raises(security.TokenError):
        security.decode_access_token(settings, token)


@pytest.mark.parametrize(
    ("issued_in", "valid_for", "accepted"),
    [
        (20, 600, True),     # issued "20 s in the future": the server clock was stepped back a little
        (300, 600, False),   # five minutes in the future is not a clock adjustment
        (-700, -10, True),   # expired 10 s ago: inside the tolerance
        (-900, -300, False),  # expired five minutes ago
    ],
)
def test_a_small_clock_step_does_not_invalidate_a_token(issued_in: int, valid_for: int, accepted: bool) -> None:
    settings = make_settings()
    now = int(time.time())
    token = jwt.encode(
        {"iss": security.TOKEN_ISSUER, "sub": "1", "iat": now + issued_in, "exp": now + valid_for},
        settings.signing_key, algorithm=security.ALGORITHM,
    )
    if accepted:
        assert security.decode_access_token(settings, token)["sub"] == "1"
    else:
        with pytest.raises(security.TokenError):
            security.decode_access_token(settings, token)
    assert security.CLOCK_LEEWAY.total_seconds() <= 60  # a tolerance, not an extension of the session


def test_token_without_expiry_is_refused() -> None:
    settings = make_settings()
    token = jwt.encode({"iss": security.TOKEN_ISSUER, "sub": "1", "iat": int(time.time())}, settings.signing_key,
                       algorithm=security.ALGORITHM)
    with pytest.raises(security.TokenError):
        security.decode_access_token(settings, token)


def test_token_from_another_issuer_is_refused() -> None:
    settings = make_settings()
    now = int(time.time())
    token = jwt.encode({"iss": "someone-else", "sub": "1", "iat": now, "exp": now + 600}, settings.signing_key,
                       algorithm=security.ALGORITHM)
    with pytest.raises(security.TokenError):
        security.decode_access_token(settings, token)


def _b64(data: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def test_unsigned_token_is_refused() -> None:
    """The classic 'alg: none' forgery."""
    now = int(time.time())
    forged = (
        _b64({"alg": "none", "typ": "JWT"}) + "."
        + _b64({"iss": security.TOKEN_ISSUER, "sub": "1", "role": "ADMIN", "iat": now, "exp": now + 600}) + "."
    )
    with pytest.raises(security.TokenError):
        security.decode_access_token(make_settings(), forged)


def test_tampered_payload_is_refused() -> None:
    settings = make_settings()
    token, _ = security.create_access_token(settings, user_id=7, role="VIEWER", is_demo=False)
    header, _payload, signature = token.split(".")
    now = int(time.time())
    forged = _b64({"iss": security.TOKEN_ISSUER, "sub": "7", "role": "ADMIN", "iat": now, "exp": now + 600})
    with pytest.raises(security.TokenError):
        security.decode_access_token(settings, f"{header}.{forged}.{signature}")


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "Bearer x"])
def test_garbage_is_refused(garbage: str) -> None:
    with pytest.raises(security.TokenError):
        security.decode_access_token(make_settings(), garbage)


def test_without_a_configured_key_tokens_last_for_the_process_only() -> None:
    settings = make_settings(secret_key=None)
    assert settings.secret_key_is_ephemeral
    assert len(settings.signing_key) >= 32
    token, _ = security.create_access_token(settings, user_id=1, role="ADMIN", is_demo=False)
    assert security.decode_access_token(make_settings(secret_key=None), token)["sub"] == "1"


def test_limiter_blocks_after_the_allowed_failures_and_recovers() -> None:
    limiter = security.AttemptLimiter(max_attempts=3, window_seconds=60)
    for _ in range(2):
        limiter.record_failure("k")
    assert limiter.blocked_for("k") == 0
    limiter.record_failure("k")
    assert 0 < limiter.blocked_for("k") <= 60
    assert limiter.blocked_for("other") == 0
    limiter.reset("k")
    assert limiter.blocked_for("k") == 0


def test_limiter_forgets_failures_outside_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(security.time, "monotonic", lambda: clock[0])
    limiter = security.AttemptLimiter(max_attempts=2, window_seconds=30)
    limiter.record_failure("k")
    limiter.record_failure("k")
    assert limiter.blocked_for("k") == pytest.approx(30)
    clock[0] += 31
    assert limiter.blocked_for("k") == 0
