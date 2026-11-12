"""HTTP: a success is announced only once the data are stored."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.types import Message, Receive, Scope, Send

from solarwise.api.app import create_app
from solarwise.db.models import User
from tests.conftest import make_settings

API = "/api/v1"
pytestmark = pytest.mark.safety


def test_a_success_is_announced_only_after_the_data_is_stored(tmp_path: Path) -> None:
    """A client acts on an answer at once: it uses the token, or opens the page of what it has just created.

    If the answer left before the transaction was committed, that next request could be refused - the account or
    the record "does not exist yet".
    """
    database = tmp_path / "durable.db"
    application = create_app(make_settings(database_url=f"sqlite:///{database}", demo_mode=True))
    stored_when_announced: list[int] = []

    async def observed(scope: Scope, receive: Receive, send: Send) -> None:
        async def checking_send(message: Message) -> None:
            announced = scope["type"] == "http" and message["type"] == "http.response.start"
            if announced and scope["path"].endswith("/auth/demo-login"):
                # Another connection sees committed data only.
                with closing(sqlite3.connect(database)) as other:
                    count = other.execute("select count(*) from users where is_demo = 1").fetchone()[0]
                stored_when_announced.append(count)
            await send(message)

        await application(scope, receive, checking_send)

    with TestClient(observed) as client:
        for _ in range(2):
            token = client.post(f"{API}/auth/demo-login").json()["access_token"]
            assert client.get(f"{API}/plants", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert stored_when_announced == [1, 2]


def test_a_write_that_cannot_be_stored_is_not_announced_as_a_success(monkeypatch: pytest.MonkeyPatch) -> None:
    application = create_app(make_settings(demo_mode=True))
    with TestClient(application, raise_server_exceptions=False) as client:

        def failing_commit(self: Session) -> None:
            raise OperationalError("COMMIT", {}, Exception("disk I/O error"))

        with monkeypatch.context() as patch:
            patch.setattr(Session, "commit", failing_commit)
            refused = client.post(f"{API}/auth/demo-login")
        assert refused.status_code == 500
        assert refused.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "access_token" not in refused.text and "disk I/O" not in refused.text

        # Nothing of the failed attempt is left, and the next one works.
        accepted = client.post(f"{API}/auth/demo-login")
        assert accepted.status_code == 200
        headers = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
        assert client.get(f"{API}/auth/me", headers=headers).status_code == 200
        with application.state.session_factory() as db:
            assert db.scalar(select(func.count()).select_from(User).where(User.is_demo)) == 1
