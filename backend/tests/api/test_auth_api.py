"""HTTP: sign-in, accounts, and who may reach what."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from solarwise import security
from solarwise.api.app import create_app
from solarwise.api.deps import TOKEN_HEADER
from solarwise.db.models import AuditLog, User
from tests import support
from tests.conftest import login, make_settings

pytestmark = pytest.mark.safety

API = "/api/v1"


def test_login_returns_a_bearer_token_and_the_account(client: TestClient) -> None:
    response = client.post(f"{API}/auth/login", json={"email": support.ENGINEER_EMAIL, "password": support.ENGINEER_PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer" and body["user"]["role"] == "ENGINEER"
    assert "password" not in str(body).lower()
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == support.ENGINEER_EMAIL


def test_failed_logins_are_indistinguishable(client: TestClient) -> None:
    wrong = client.post(f"{API}/auth/login", json={"email": support.ENGINEER_EMAIL, "password": "definitely wrong"})
    unknown = client.post(f"{API}/auth/login", json={"email": "nobody@example.org", "password": "definitely wrong"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_repeated_failures_are_throttled_and_then_even_the_right_password_waits(client: TestClient) -> None:
    for _ in range(5):
        assert client.post(f"{API}/auth/login", json={"email": support.VIEWER_EMAIL, "password": "wrong wrong wrong"}).status_code == 401
    blocked = client.post(f"{API}/auth/login", json={"email": support.VIEWER_EMAIL, "password": support.VIEWER_PASSWORD})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0
    # Another account from the same address is not locked out by it.
    assert client.post(f"{API}/auth/login", json={"email": support.ADMIN_EMAIL, "password": support.ADMIN_PASSWORD}).status_code == 200


def test_failed_attempts_survive_the_failed_request(client: TestClient, app: FastAPI) -> None:
    """The counter must be committed although the request itself fails."""
    client.post(f"{API}/auth/login", json={"email": support.ENGINEER_EMAIL, "password": "wrong wrong wrong"})
    with app.state.session_factory() as session:
        from solarwise.services import users as user_service

        user = user_service.get_by_email(session, support.ENGINEER_EMAIL)
        assert user is not None and user.failed_logins == 1


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-token"}, {"Authorization": "Basic dXNlcjpwYXNz"}, {"Authorization": "Bearer "}],
)
def test_protected_endpoints_require_a_valid_token(client: TestClient, headers: dict[str, str]) -> None:
    for method, path in (
        ("GET", "/plants"), ("GET", "/auth/me"), ("GET", "/reference/schema"), ("GET", "/reference/economic"),
        ("GET", "/reference/decision-rules"), ("GET", "/analyses/1"), ("GET", "/datasets/1"), ("GET", "/users"),
        ("POST", "/economics/calculate"), ("POST", "/recommendations/evaluate"), ("GET", "/analyses/1/report.pdf"),
    ):
        response = client.request(method, f"{API}{path}", headers=headers)
        assert response.status_code == 401, (method, path, response.status_code)
        assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"
        assert response.headers["www-authenticate"] == "Bearer"


def test_only_health_and_meta_are_public(client: TestClient) -> None:
    assert client.get(f"{API}/health").json() == {"status": "ok", "database": "ok"}
    meta = client.get(f"{API}/meta").json()
    assert meta["demo_mode"] is False and meta["ai"]["enabled"] is False
    assert "secret" not in str(meta).lower() and "database_url" not in str(meta).lower()


def test_token_of_a_deactivated_account_stops_working(client: TestClient, admin: dict[str, str], engineer: dict[str, str]) -> None:
    users = client.get(f"{API}/users", headers=admin).json()
    target = next(u for u in users if u["email"] == support.ENGINEER_EMAIL)
    assert client.patch(f"{API}/users/{target['id']}", json={"is_active": False}, headers=admin).status_code == 200
    assert client.get(f"{API}/plants", headers=engineer).status_code == 401


def test_the_token_is_also_accepted_in_a_header_of_its_own(client: TestClient, engineer: dict[str, str]) -> None:
    """Some proxies remove the Authorization header, or put a credential of their own in it."""
    token = engineer["Authorization"].removeprefix("Bearer ")
    for headers in (
        {TOKEN_HEADER: token},
        {TOKEN_HEADER: token, "Authorization": "Bearer credential-of-the-gateway"},
        {TOKEN_HEADER: token, "Authorization": "Basic Z2F0ZXdheTpzZWNyZXQ="},
    ):
        response = client.get(f"{API}/auth/me", headers=headers)
        assert response.status_code == 200, headers
        assert response.json()["email"] == support.ENGINEER_EMAIL


def test_the_token_header_is_checked_exactly_like_the_authorization_header(
    client: TestClient, admin: dict[str, str], engineer: dict[str, str]
) -> None:
    forged, _ = security.create_access_token(make_settings(secret_key="attacker-key-" * 4), user_id=1, role="ADMIN", is_demo=False)
    for bad in ("not-a-token", "", "   ", forged):
        response = client.get(f"{API}/users", headers={TOKEN_HEADER: bad})
        assert response.status_code == 401 and response.json()["error"]["code"] == "NOT_AUTHENTICATED"
    token = engineer["Authorization"].removeprefix("Bearer ")
    assert client.get(f"{API}/users", headers={TOKEN_HEADER: token}).status_code == 403  # no privilege gained
    users = client.get(f"{API}/users", headers=admin).json()
    engineer_id = next(u["id"] for u in users if u["email"] == support.ENGINEER_EMAIL)
    assert client.patch(f"{API}/users/{engineer_id}", json={"is_active": False}, headers=admin).status_code == 200
    assert client.get(f"{API}/auth/me", headers={TOKEN_HEADER: token}).status_code == 401


def test_the_reason_of_a_refusal_is_logged_without_the_token(
    client: TestClient, engineer: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    token = engineer["Authorization"].removeprefix("Bearer ")
    with caplog.at_level("INFO", logger="solarwise.api"):
        client.get(f"{API}/plants")
        client.get(f"{API}/plants", headers={"Authorization": "Bearer not-a-token"})
        client.get(f"{API}/plants", headers={TOKEN_HEADER: token})
        client.get(f"{API}/plants", headers={TOKEN_HEADER: token})
    text = caplog.text
    assert "401 on GET /api/v1/plants: no access token was received" in text
    assert "401 on GET /api/v1/plants: access token not accepted (Authorization: DecodeError)" in text
    # The operator is told once that something in front of the server removes the Authorization header.
    assert text.count("because its Authorization header was missing on arrival") == 1
    assert token not in text and "not-a-token" not in text


def test_token_signed_by_someone_else_is_refused(client: TestClient) -> None:
    forged, _ = security.create_access_token(make_settings(secret_key="attacker-key-" * 4), user_id=1, role="ADMIN", is_demo=False)
    assert client.get(f"{API}/users", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_role_claim_in_the_token_is_not_trusted(client: TestClient, app: FastAPI) -> None:
    """The role is read from the database: a token claiming ADMIN for a viewer gives nothing."""
    with app.state.session_factory() as session:
        from solarwise.services import users as user_service

        viewer = user_service.get_by_email(session, support.VIEWER_EMAIL)
        assert viewer is not None
        token, _ = security.create_access_token(app.state.settings, user_id=viewer.id, role="ADMIN", is_demo=False)
    assert client.get(f"{API}/users", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_account_management_is_for_administrators(client: TestClient, admin: dict[str, str], engineer: dict[str, str]) -> None:
    payload = {"email": "new@example.org", "password": "a brand new long passphrase", "role": "ENGINEER"}
    assert client.post(f"{API}/users", json=payload, headers=engineer).status_code == 403
    assert client.get(f"{API}/users", headers=engineer).status_code == 403
    created = client.post(f"{API}/users", json=payload, headers=admin)
    assert created.status_code == 201 and created.json()["role"] == "ENGINEER"
    assert client.post(f"{API}/users", json=payload, headers=admin).status_code == 409
    weak = client.post(f"{API}/users", json={**payload, "email": "weak@example.org", "password": "short"}, headers=admin)
    assert weak.status_code == 422 and weak.json()["error"]["code"] == "WEAK_PASSWORD"
    assert login(client, "new@example.org", "a brand new long passphrase")


def test_an_administrator_cannot_lock_themselves_out(client: TestClient, admin: dict[str, str]) -> None:
    me = client.get(f"{API}/auth/me", headers=admin).json()
    assert client.patch(f"{API}/users/{me['id']}", json={"is_active": False}, headers=admin).status_code == 409
    assert client.patch(f"{API}/users/{me['id']}", json={"role": "VIEWER"}, headers=admin).status_code == 409


def test_plants_of_others_do_not_exist_for_you(client: TestClient, engineer: dict[str, str], viewer: dict[str, str],
                                                admin: dict[str, str], plant_id: int, dataset_id: int) -> None:
    run = client.post(f"{API}/datasets/{dataset_id}/analyses", json={"options": {}}, headers=engineer)
    assert run.status_code == 201
    analysis_id = run.json()["id"]
    assert client.get(f"{API}/plants", headers=viewer).json() == []
    for method, path in (
        ("GET", f"/plants/{plant_id}"), ("GET", f"/plants/{plant_id}/datasets"), ("GET", f"/plants/{plant_id}/devices"),
        ("GET", f"/plants/{plant_id}/evidence"), ("GET", f"/plants/{plant_id}/analyses"),
        ("GET", f"/datasets/{dataset_id}"), ("GET", f"/datasets/{dataset_id}/series"),
        ("GET", f"/analyses/{analysis_id}"), ("GET", f"/analyses/{analysis_id}/report.json"),
        ("GET", f"/analyses/{analysis_id}/forecast"), ("POST", f"/analyses/{analysis_id}/explanation"),
        ("DELETE", f"/plants/{plant_id}"), ("DELETE", f"/datasets/{dataset_id}"),
    ):
        response = client.request(method, f"{API}{path}", headers=viewer)
        assert response.status_code == 404, (method, path, response.status_code)
    # The administrator sees it.
    assert client.get(f"{API}/plants/{plant_id}", headers=admin).status_code == 200


def test_read_access_does_not_allow_changes(client: TestClient, engineer: dict[str, str], viewer: dict[str, str],
                                            plant_id: int, dataset_id: int) -> None:
    grant = client.put(f"{API}/plants/{plant_id}/permissions", json={"email": support.VIEWER_EMAIL, "role": "VIEWER"},
                       headers=engineer)
    assert grant.status_code == 200
    assert client.get(f"{API}/plants/{plant_id}", headers=viewer).json()["role"] == "VIEWER"
    assert client.get(f"{API}/datasets/{dataset_id}", headers=viewer).status_code == 200
    forbidden = [
        client.patch(f"{API}/plants/{plant_id}", json={"spec": {"name": "x"}}, headers=viewer),
        client.delete(f"{API}/plants/{plant_id}", headers=viewer),
        client.post(f"{API}/plants/{plant_id}/devices", json={"code": "X", "capacity_kwp": 1}, headers=viewer),
        client.post(f"{API}/plants/{plant_id}/datasets", headers=viewer, **support.upload_parts(support.daily_csv(days=5))),
        client.post(f"{API}/datasets/{dataset_id}/analyses", json={"options": {}}, headers=viewer),
        client.delete(f"{API}/datasets/{dataset_id}", headers=viewer),
        client.get(f"{API}/plants/{plant_id}/permissions", headers=viewer),
        client.put(f"{API}/plants/{plant_id}/permissions", json={"email": support.VIEWER_EMAIL, "role": "OWNER"}, headers=viewer),
    ]
    assert [r.status_code for r in forbidden] == [403] * len(forbidden)
    # Validation writes nothing, so a reader may use it.
    check = client.post(f"{API}/plants/{plant_id}/datasets/validate", headers=viewer,
                        **support.upload_parts(support.daily_csv(days=5)))
    assert check.status_code == 200 and check.json()["stored"] is False


def test_a_plant_keeps_at_least_one_owner(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    owners = client.get(f"{API}/plants/{plant_id}/permissions", headers=engineer).json()
    assert [p["role"] for p in owners] == ["OWNER"]
    response = client.delete(f"{API}/plants/{plant_id}/permissions/{owners[0]['user_id']}", headers=engineer)
    assert response.status_code == 409


# --------------------------------------------------------------------------- sign-up

NEW = {"email": "new.person@example.org", "password": "a passphrase nobody else uses", "full_name": "New Person"}
ROOT = {"email": "root@example.org", "password": "the administrator's own passphrase"}


def sign_up(client: TestClient, **changes: str) -> dict[str, str]:
    response = client.post(f"{API}/auth/register", json={**NEW, **changes})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def accounts(app: FastAPI) -> int:
    with app.state.session_factory() as session:
        return int(session.scalar(select(func.count()).select_from(User)) or 0)


def test_sign_up_creates_an_engineer_account_and_signs_it_in(client: TestClient) -> None:
    response = client.post(f"{API}/auth/register", json={**NEW, "email": "  New.Person@Example.org "})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"] == {
        "id": body["user"]["id"], "email": NEW["email"], "full_name": "New Person", "role": "ENGINEER",
        "is_demo": False, "is_active": True,
    }
    assert NEW["password"] not in response.text
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json() == body["user"]
    # The password it chose opens the next session.
    assert login(client, NEW["email"], NEW["password"])


def test_the_token_of_a_sign_up_is_accepted_in_the_header_of_its_own(client: TestClient) -> None:
    """Behind a proxy that removes the Authorization header, a new account must not be signed out at once."""
    token = sign_up(client)["Authorization"].removeprefix("Bearer ")
    assert client.get(f"{API}/plants", headers={TOKEN_HEADER: token}).status_code == 200


def test_a_new_account_starts_empty_and_sees_nothing_of_the_others(
    client: TestClient, engineer: dict[str, str], plant_id: int
) -> None:
    headers = sign_up(client)
    assert client.get(f"{API}/plants", headers=headers).json() == []
    assert client.get(f"{API}/plants/{plant_id}", headers=headers).status_code == 404
    assert client.get(f"{API}/users", headers=headers).status_code == 403
    own = client.post(f"{API}/plants", json=support.PLANT_PAYLOAD, headers=headers)
    assert own.status_code == 201, own.text
    assert own.json()["role"] == "OWNER" and own.json()["is_demonstration"] is False
    # ... and nobody else sees what it registers.
    assert client.get(f"{API}/plants/{own.json()['id']}", headers=engineer).status_code == 404


@pytest.mark.parametrize("extra", [{"role": "ADMIN"}, {"role": "ENGINEER"}, {"is_admin": True}, {"is_demo": True}])
def test_sign_up_cannot_name_a_role_or_any_other_privilege(client: TestClient, app: FastAPI, extra: dict[str, object]) -> None:
    before = accounts(app)
    response = client.post(f"{API}/auth/register", json={**NEW, **extra})
    assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID"
    assert accounts(app) == before


def test_sign_up_never_takes_over_an_address_that_is_registered(client: TestClient, app: FastAPI) -> None:
    before = accounts(app)
    taken = client.post(f"{API}/auth/register", json={**NEW, "email": support.ENGINEER_EMAIL.upper()})
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "EMAIL_TAKEN"
    assert accounts(app) == before
    # The account is untouched: its own password still works, the other one does not.
    assert login(client, support.ENGINEER_EMAIL, support.ENGINEER_PASSWORD)
    impostor = client.post(f"{API}/auth/login", json={"email": support.ENGINEER_EMAIL, "password": NEW["password"]})
    assert impostor.status_code == 401


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"password": "short"}, "WEAK_PASSWORD"),
        ({"password": "aaaaaaaaaaaaaaaaaaaa"}, "WEAK_PASSWORD"),
        ({"password": " a passphrase with a space first"}, "WEAK_PASSWORD"),
        ({"email": "not an address"}, "INVALID_EMAIL"),
        ({"email": "visitor@solarwise.invalid"}, "INVALID_EMAIL"),
        ({"full_name": "   "}, "INVALID"),
        ({"full_name": ""}, "INVALID"),
        ({"password": None}, "INVALID"),
    ],
)
def test_sign_up_applies_the_rules_of_every_account(
    client: TestClient, app: FastAPI, change: dict[str, str | None], code: str
) -> None:
    before = accounts(app)
    response = client.post(f"{API}/auth/register", json={**NEW, **change})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code
    assert accounts(app) == before


def test_the_server_says_whether_sign_up_is_open(client: TestClient) -> None:
    assert client.get(f"{API}/meta").json()["registration_open"] is True


def test_sign_up_can_be_switched_off() -> None:
    application = create_app(make_settings(allow_registration=False))
    with TestClient(application) as closed:
        assert closed.get(f"{API}/meta").json()["registration_open"] is False
        response = closed.post(f"{API}/auth/register", json=NEW)
        assert response.status_code == 403 and response.json()["error"]["code"] == "REGISTRATION_CLOSED"
        assert accounts(application) == 0


def test_sign_up_is_limited_per_address_and_refused_attempts_count(client: TestClient, app: FastAPI) -> None:
    app.state.registration_limiter = security.AttemptLimiter(2, 600)
    before = accounts(app)
    assert client.post(f"{API}/auth/register", json={**NEW, "email": support.ADMIN_EMAIL}).status_code == 409
    assert client.post(f"{API}/auth/register", json=NEW).status_code == 201
    blocked = client.post(f"{API}/auth/register", json={**NEW, "email": "third@example.org"})
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "TOO_MANY_REQUESTS"
    assert int(blocked.headers["retry-after"]) > 0
    assert accounts(app) == before + 1
    # Signing in is not affected by it.
    assert login(client, NEW["email"], NEW["password"])


def test_sign_up_is_written_to_the_audit_trail_without_the_password(client: TestClient, app: FastAPI) -> None:
    created = client.post(f"{API}/auth/register", json=NEW).json()["user"]
    with app.state.session_factory() as session:
        entry = session.scalars(select(AuditLog).where(AuditLog.action == "USER_REGISTERED")).one()
        assert (entry.user_id, entry.entity, entry.entity_id) == (created["id"], "user", created["id"])
        assert entry.remote_address
        assert NEW["password"] not in str(entry.detail)


def test_an_administrator_can_close_an_account_that_signed_up(client: TestClient, admin: dict[str, str]) -> None:
    created = client.post(f"{API}/auth/register", json=NEW).json()
    headers = {"Authorization": f"Bearer {created['access_token']}"}
    listed = {u["email"]: u for u in client.get(f"{API}/users", headers=admin).json()}
    assert listed[NEW["email"]]["role"] == "ENGINEER"
    closed = client.patch(f"{API}/users/{created['user']['id']}", json={"is_active": False}, headers=admin)
    assert closed.status_code == 200
    assert client.get(f"{API}/auth/me", headers=headers).status_code == 401
    again = client.post(f"{API}/auth/login", json={"email": NEW["email"], "password": NEW["password"]})
    assert again.status_code == 401
    # The address stays taken: a closed account cannot be replaced by signing up again.
    assert client.post(f"{API}/auth/register", json=NEW).status_code == 409


def test_an_account_created_while_the_demonstration_is_on_is_not_a_demonstration_session(demo_client: TestClient) -> None:
    created = demo_client.post(f"{API}/auth/register", json={**NEW, "email": "real.account@example.org"})
    assert created.status_code == 201, created.text
    assert created.json()["user"]["is_demo"] is False
    headers = {"Authorization": f"Bearer {created.json()['access_token']}"}
    # The shared demonstration plant belongs to demonstration sessions; an account starts with its own, empty list.
    assert demo_client.get(f"{API}/plants", headers=headers).json() == []
    own = demo_client.post(f"{API}/plants", json=support.PLANT_PAYLOAD, headers=headers)
    assert own.status_code == 201 and own.json()["is_demonstration"] is False


def test_start_up_creates_the_first_administrator_although_people_signed_up_before(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'installation.db'}"
    with TestClient(create_app(make_settings(database_url=url))) as first:
        sign_up(first)
    boot = make_settings(database_url=url, bootstrap_admin_email=ROOT["email"], bootstrap_admin_password=ROOT["password"])
    with TestClient(create_app(boot)) as second:
        headers = login(second, ROOT["email"], ROOT["password"])
        roles = {u["email"]: u["role"] for u in second.get(f"{API}/users", headers=headers).json()}
        assert roles == {ROOT["email"]: "ADMIN", NEW["email"]: "ENGINEER"}
    # Once it exists, other bootstrap values change nothing.
    later = make_settings(database_url=url, bootstrap_admin_email="other@example.org", bootstrap_admin_password=ROOT["password"])
    with TestClient(create_app(later)) as third:
        refused = third.post(f"{API}/auth/login", json={"email": "other@example.org", "password": ROOT["password"]})
        assert refused.status_code == 401


def test_start_up_does_not_promote_an_account_that_took_the_administrators_address(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    url = f"sqlite:///{tmp_path / 'installation.db'}"
    with TestClient(create_app(make_settings(database_url=url))) as first:
        sign_up(first, email=ROOT["email"])
    boot = make_settings(database_url=url, bootstrap_admin_email=ROOT["email"], bootstrap_admin_password=ROOT["password"])
    with caplog.at_level(logging.ERROR, logger="solarwise"), TestClient(create_app(boot)) as second:
        # The server starts all the same, and the account is what it was: an engineer, with its own password.
        refused = second.post(f"{API}/auth/login", json={"email": ROOT["email"], "password": ROOT["password"]})
        assert refused.status_code == 401
        headers = login(second, ROOT["email"], NEW["password"])
        assert second.get(f"{API}/auth/me", headers=headers).json()["role"] == "ENGINEER"
        assert second.get(f"{API}/users", headers=headers).status_code == 403
    assert "no administrator was created" in caplog.text
    assert ROOT["password"] not in caplog.text


# --------------------------------------------------------------------------- demonstration sign-in


def test_demo_login_does_not_exist_unless_demo_mode_is_on(client: TestClient) -> None:
    response = client.post(f"{API}/auth/demo-login")
    assert response.status_code == 404


def test_demo_login_gives_each_visit_its_own_read_only_view(demo_client: TestClient) -> None:
    first = demo_client.post(f"{API}/auth/demo-login").json()
    second = demo_client.post(f"{API}/auth/demo-login").json()
    assert first["user"]["is_demo"] and second["user"]["is_demo"]
    assert first["user"]["id"] != second["user"]["id"]
    headers = {"Authorization": f"Bearer {first['access_token']}"}
    plants = demo_client.get(f"{API}/plants", headers=headers).json()
    assert len(plants) == 1 and plants[0]["is_demonstration"] and plants[0]["role"] == "VIEWER"
    assert demo_client.get(f"{API}/users", headers=headers).status_code == 403


def test_a_demo_token_is_worthless_once_demo_mode_is_off(demo_client: TestClient, demo_app: FastAPI) -> None:
    token = demo_client.post(f"{API}/auth/demo-login").json()["access_token"]
    # Same database and signing key, demonstration switched off.
    settings = make_settings(demo_mode=False)
    other = create_app(settings)
    other.state.session_factory = demo_app.state.session_factory
    with TestClient(other, raise_server_exceptions=False) as plain:
        other.state.session_factory = demo_app.state.session_factory
        response = plain.get(f"{API}/plants", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_opening_demo_sessions_is_rate_limited(demo_client: TestClient, demo_app: FastAPI) -> None:
    demo_app.state.demo_limiter = security.AttemptLimiter(2, 300)
    try:
        assert demo_client.post(f"{API}/auth/demo-login").status_code == 200
        assert demo_client.post(f"{API}/auth/demo-login").status_code == 200
        assert demo_client.post(f"{API}/auth/demo-login").status_code == 429
    finally:
        demo_app.state.demo_limiter = security.AttemptLimiter(60, 300)
