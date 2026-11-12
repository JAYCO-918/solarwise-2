"""The fixtures of the web interface's tests are what the server sends today."""

from __future__ import annotations

import pytest

from tests import frontend_fixtures


@pytest.mark.skipif(not frontend_fixtures.FIXTURE_DIR.is_dir(), reason="no frontend checkout next to the backend")
def test_frontend_fixtures_are_current() -> None:
    built = frontend_fixtures.build()
    stored = {path.stem: path.read_text(encoding="utf-8") for path in frontend_fixtures.FIXTURE_DIR.glob("*.json")}
    assert set(stored) == set(built), "run `python -m tests.frontend_fixtures` from backend/"
    stale = [name for name, payload in built.items() if stored[name] != frontend_fixtures.render(payload)]
    assert not stale, f"out of date: {stale}; run `python -m tests.frontend_fixtures` from backend/"


def test_fixtures_do_not_depend_on_when_they_were_built() -> None:
    assert frontend_fixtures.render(frontend_fixtures.build()) == frontend_fixtures.render(frontend_fixtures.build())
