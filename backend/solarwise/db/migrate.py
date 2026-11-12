"""Bringing a database to the current schema."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect

from solarwise.db import models  # noqa: F401 - registers the tables on the metadata
from solarwise.db.base import Base

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    return config


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def upgrade(engine: Engine) -> None:
    """Apply every pending migration."""
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def init_schema(engine: Engine) -> str:
    """Create or upgrade the schema.  Returns how it was done.

    An in-memory database (tests) is created directly from the models.  Any
    other database goes through the migrations, so that the schema in use is
    always one that a migration produced.
    """
    url = engine.url
    if url.get_backend_name() == "sqlite" and url.database in (None, "", ":memory:"):
        Base.metadata.create_all(engine)
        return "created from models (in-memory database)"
    tables = set(inspect(engine).get_table_names())
    if tables and "alembic_version" not in tables:
        raise RuntimeError(
            "the database contains tables but no migration history; refusing to guess its state. "
            "Use an empty database, or stamp it with `alembic stamp` after checking its schema."
        )
    before = current_revision(engine)
    upgrade(engine)
    after = current_revision(engine)
    return f"migrated {before or 'empty'} -> {after}" if before != after else f"up to date ({after})"
