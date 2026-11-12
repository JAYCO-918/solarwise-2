"""Fixtures shared by the service and API tests."""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from solarwise.api.app import create_app
from solarwise.config import Settings
from solarwise.db.base import Base, build_engine, build_session_factory
from solarwise.db.models import Role, User
from solarwise.services import users as user_service
from tests import support

#: Optional: a database server to run the service and API tests on, for example PostgreSQL
#: (``postgresql+psycopg://user:password@host/postgres``).  The account must be allowed to create databases: every
#: application and every session of the tests gets a database of its own, exactly as it gets its own in-memory SQLite
#: database when this is unset.  They are dropped at the end of the run.
TEST_DATABASE_URL = os.environ.get("SOLARWISE_TEST_DATABASE_URL") or None

_created_databases: list[str] = []


def fresh_database_url() -> str:
    """URL of a database nothing else uses."""
    if not TEST_DATABASE_URL:
        return "sqlite://"
    name = f"solarwise_test_{secrets.token_hex(6)}"
    server = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        with server.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    finally:
        server.dispose()
    _created_databases.append(name)
    return make_url(TEST_DATABASE_URL).set(database=name).render_as_string(hide_password=False)


@pytest.fixture(scope="session", autouse=True)
def _drop_test_databases() -> Iterator[None]:
    yield
    if not _created_databases or not TEST_DATABASE_URL:
        return
    server = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        with server.connect() as connection:
            for name in _created_databases:
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        server.dispose()


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "database_url": None,
        "secret_key": "test-secret-key-test-secret-key-test-secret-key",
        "external_data_enabled": True,
        "_env_file": None,
    }
    values.update(overrides)
    if values["database_url"] is None:
        values["database_url"] = fresh_database_url()
    return Settings(**values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def db() -> Iterator[Session]:
    """A session on a fresh database (no HTTP layer): in memory, unless another one is configured."""
    engine = build_engine(fresh_database_url())
    Base.metadata.create_all(engine)
    session = build_session_factory(engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _accounts(app: FastAPI) -> None:
    with app.state.session_factory() as session:
        for email, password, role in (
            (support.ADMIN_EMAIL, support.ADMIN_PASSWORD, Role.ADMIN),
            (support.ENGINEER_EMAIL, support.ENGINEER_PASSWORD, Role.ENGINEER),
            (support.VIEWER_EMAIL, support.VIEWER_PASSWORD, Role.VIEWER),
        ):
            user_service.create_user(session, email=email, password=password, full_name=role.value.title(), role=role)
        session.commit()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """A running server (start-up and shut-down included) with one account of each role."""
    application = create_app(settings)
    with TestClient(application) as test_client:
        _accounts(application)
        yield test_client


@pytest.fixture
def app(client: TestClient) -> FastAPI:
    application = client.app
    assert isinstance(application, FastAPI)
    return application


def login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin(client: TestClient) -> dict[str, str]:
    return login(client, support.ADMIN_EMAIL, support.ADMIN_PASSWORD)


@pytest.fixture
def engineer(client: TestClient) -> dict[str, str]:
    return login(client, support.ENGINEER_EMAIL, support.ENGINEER_PASSWORD)


@pytest.fixture
def viewer(client: TestClient) -> dict[str, str]:
    return login(client, support.VIEWER_EMAIL, support.VIEWER_PASSWORD)


@pytest.fixture
def plant_id(client: TestClient, engineer: dict[str, str]) -> int:
    response = client.post("/api/v1/plants", json=support.PLANT_PAYLOAD, headers=engineer)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


@pytest.fixture
def dataset_id(client: TestClient, engineer: dict[str, str], plant_id: int) -> int:
    response = client.post(
        f"/api/v1/plants/{plant_id}/datasets", headers=engineer, **support.upload_parts(support.daily_csv())
    )
    assert response.status_code == 201, response.text
    return int(response.json()["dataset"]["id"])


# --------------------------------------------------------------------------- demonstration server


@pytest.fixture(scope="module")
def demo_client() -> Iterator[TestClient]:
    """A server in demonstration mode, started and seeded once per test module."""
    application = create_app(make_settings(demo_mode=True))
    with TestClient(application) as test_client:
        _accounts(application)
        yield test_client


@pytest.fixture
def demo_app(demo_client: TestClient) -> FastAPI:
    application = demo_client.app
    assert isinstance(application, FastAPI)
    return application


@pytest.fixture
def visitor(demo_client: TestClient) -> dict[str, str]:
    """Headers of a fresh demonstration session."""
    response = demo_client.post("/api/v1/auth/demo-login")
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def user_of(session: Session, email: str) -> User:
    user = user_service.get_by_email(session, email)
    assert user is not None
    return user
