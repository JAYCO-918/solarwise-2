"""Storage: UTC timestamps, NULL preserved, migrations equal to the models, cascades."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from solarwise.db.base import Base, build_engine, build_session_factory, session_scope
from solarwise.db.migrate import current_revision, head_revision, init_schema
from solarwise.db.models import (
    Analysis,
    AuditLog,
    Dataset,
    Device,
    EvidenceRow,
    Plant,
    PlantPermission,
    ProductionObservation,
    User,
    WeatherObservation,
)
from solarwise.services import datasets as dataset_service
from solarwise.services import plants as plant_service
from solarwise.services import users as user_service
from tests import support
from tests.builders import PLANT


def _user(db: Session, email: str = "someone@example.org") -> User:
    return user_service.create_user(db, email=email, password="a long and unusual passphrase")


def test_naive_timestamps_are_refused(db: Session) -> None:
    db.add(AuditLog(action="TEST", at=datetime(2026, 5, 1, 12, 0)))
    with pytest.raises(StatementError, match="naive datetime refused"):
        db.flush()


def test_timestamps_come_back_as_aware_utc(db: Session) -> None:
    algiers = timezone(timedelta(hours=1))
    db.add(AuditLog(action="TEST", at=datetime(2026, 5, 1, 12, 0, tzinfo=algiers)))
    db.commit()
    db.expire_all()
    stored = db.scalars(select(AuditLog)).one().at
    assert stored == datetime(2026, 5, 1, 11, 0, tzinfo=UTC)
    assert stored.utcoffset() == timedelta(0)


def test_sqlite_enforces_foreign_keys(db: Session) -> None:
    db.add(PlantPermission(plant_id=999, user_id=999, role="VIEWER"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_migrations_produce_exactly_the_schema_of_the_models(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'migrated.db'}")
    assert init_schema(engine).startswith("migrated empty")
    assert current_revision(engine) == head_revision()
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata)
    assert differences == []
    assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_migrating_twice_changes_nothing(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'twice.db'}")
    init_schema(engine)
    assert init_schema(engine).startswith("up to date")
    engine.dispose()


def test_a_database_of_unknown_state_is_not_touched(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'foreign.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE something_else (id INTEGER PRIMARY KEY)"))
    with pytest.raises(RuntimeError, match="no migration history"):
        init_schema(engine)
    assert inspect(engine).get_table_names() == ["something_else"]
    engine.dispose()


def test_file_database_directory_is_created(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "solarwise.db"
    engine = build_engine(f"sqlite:///{target}")
    init_schema(engine)
    assert target.is_file()
    engine.dispose()


def test_session_scope_rolls_back_on_error() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with pytest.raises(RuntimeError), session_scope(factory) as session:
        session.add(AuditLog(action="NEVER_STORED"))
        session.flush()
        raise RuntimeError("boom")
    with session_scope(factory) as session:
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 0
    engine.dispose()


def _import(db: Session, plant: Plant, user: User, csv_text: str) -> Dataset:
    import json

    checked = dataset_service.check_upload(
        db, plant, data=csv_text.encode(), filename="data.csv", content_type="text/csv",
        metadata_json=json.dumps(support.metadata()),
    )
    assert checked.report.accepted, checked.report.summary
    return dataset_service.import_upload(db, plant, user, checked, "data.csv")


@pytest.mark.safety
def test_a_missing_value_is_stored_as_null_and_read_back_as_none(db: Session) -> None:
    """Missing is not zero: an empty cell must survive storage as 'no value'."""
    user = _user(db)
    user.role = "ENGINEER"
    plant = plant_service.create_plant(db, user, PLANT)
    dataset = _import(db, plant, user, support.daily_csv(days=10, blank_actual_days=(3, 4)))
    db.commit()
    db.expire_all()

    nulls = db.scalar(
        select(func.count()).select_from(ProductionObservation)
        .where(ProductionObservation.dataset_id == dataset.id, ProductionObservation.actual_energy_kwh.is_(None))
    )
    zeros = db.scalar(
        select(func.count()).select_from(ProductionObservation)
        .where(ProductionObservation.dataset_id == dataset.id, ProductionObservation.actual_energy_kwh == 0)
    )
    assert (nulls, zeros) == (2, 0)
    loaded = dataset_service.load_observations(db, dataset).observations
    assert [o.actual_energy_kwh is None for o in loaded] == [i in (3, 4) for i in range(10)]
    assert all(o.expected_energy_kwh == 50_000.0 for o in loaded)
    # Channels the file does not contain stay absent rather than being filled in.
    assert all(o.poa_irradiation_kwh_m2 is None for o in loaded)
    assert db.scalar(select(func.count()).select_from(WeatherObservation)) == 0


def test_stored_values_round_trip_exactly(db: Session) -> None:
    user = _user(db)
    user.role = "ENGINEER"
    plant = plant_service.create_plant(db, user, PLANT)
    dataset = _import(db, plant, user, support.daily_csv(days=5, soiling_loss=0.0375))
    loaded = dataset_service.load_observations(db, dataset).observations
    assert [o.actual_energy_kwh for o in loaded] == [pytest.approx(48_125.0)] * 5
    assert [o.soiling_ratio for o in loaded] == [pytest.approx(0.9625)] * 5
    assert loaded[0].start_utc == datetime(2026, 4, 30, 23, 0, tzinfo=UTC)  # local midnight in Algiers (UTC+1)


def test_deleting_a_plant_removes_everything_that_belongs_to_it(db: Session) -> None:
    user = _user(db)
    user.role = "ENGINEER"
    plant = plant_service.create_plant(db, user, PLANT)
    plant_service.add_device(db, plant, code="INV-1", capacity_kwp=100.0, kind="INVERTER", description="")
    _import(db, plant, user, support.daily_csv(days=5))
    db.commit()
    assert db.scalar(select(func.count()).select_from(ProductionObservation)) == 5

    db.delete(plant)
    db.commit()
    for model in (Plant, Device, PlantPermission, Dataset, ProductionObservation, EvidenceRow, Analysis):
        assert db.scalar(select(func.count()).select_from(model)) == 0, model.__name__
    assert db.scalar(select(func.count()).select_from(User)) == 1  # the account itself is kept


def test_the_same_content_cannot_be_stored_twice_for_a_plant(db: Session) -> None:
    user = _user(db)
    user.role = "ENGINEER"
    plant = plant_service.create_plant(db, user, PLANT)
    first = _import(db, plant, user, support.daily_csv(days=5))
    db.add(
        Dataset(
            plant_id=plant.id, name="copy", content_sha256=first.content_sha256, interval_minutes=1440,
            timezone="Africa/Algiers", period_start=first.period_start, period_end=first.period_end,
            declared_metadata={}, channels={}, validation_report={},
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
