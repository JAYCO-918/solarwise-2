"""Alembic environment.

Used in two ways: by the application, which passes an open connection in
``config.attributes["connection"]``; and from the command line, where the URL is
read from the same settings as the application.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from solarwise.config import get_settings
from solarwise.db import models  # noqa: F401 - registers the tables on the metadata
from solarwise.db.base import Base

config = context.config
target_metadata = Base.metadata


def _configure(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite cannot ALTER most things in place; batch mode rebuilds the table instead.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection)
        return
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = get_settings().database_url
    engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as conn:
        _configure(conn)


def run_migrations_offline() -> None:
    context.configure(url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
