"""Relational model.

* ``datasets`` are immutable: a dataset is imported once, with the declarations
  made about it, and never edited.  Corrections are a new dataset.
* Observations are stored wide, one row per interval, in canonical units.
  ``NULL`` means *not observed* - it is never a zero.
* ``analyses`` keep the complete result of a run together with the options and
  engine version that produced it, so that a past recommendation can always be
  re-read exactly as it was issued.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from solarwise.db.base import Base, UTCDateTime, utcnow


class Role(StrEnum):
    ADMIN = "ADMIN"
    ENGINEER = "ENGINEER"
    VIEWER = "VIEWER"


class PlantRole(StrEnum):
    OWNER = "OWNER"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class DatasetKind(StrEnum):
    #: Production data, optionally with weather and soiling channels.
    PRODUCTION = "PRODUCTION"
    #: Weather context only (for example NASA POWER); can complement a production dataset.
    WEATHER = "WEATHER"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str | None] = mapped_column(String(500), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default=Role.VIEWER.value)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Account of the public demonstration: everything it evaluates is a simulation.
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Plant(Base):
    __tablename__ = "plants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    capacity_dc_kwp: Mapped[float] = mapped_column(Float)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    timezone: Mapped[str] = mapped_column(String(64))
    is_demonstration: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Full engineering description (:class:`solarwise.core.models.PlantSpec`); the columns above mirror it.
    spec: Mapped[dict[str, Any]] = mapped_column(JSON)
    #: PVGIS monthly averages for the typical-year baseline, with their origin.
    pvgis_monthly: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    pvgis_source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    devices: Mapped[list[Device]] = relationship(back_populates="plant", cascade="all, delete-orphan")
    permissions: Mapped[list[PlantPermission]] = relationship(back_populates="plant", cascade="all, delete-orphan")


class PlantPermission(Base):
    __tablename__ = "plant_permissions"
    __table_args__ = (UniqueConstraint("plant_id", "user_id", name="uq_plant_permission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default=PlantRole.VIEWER.value)

    plant: Mapped[Plant] = relationship(back_populates="permissions")


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("plant_id", "code", name="uq_device_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(30), default="INVERTER")
    capacity_kwp: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(String(500), default="")

    plant: Mapped[Plant] = relationship(back_populates="devices")


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("plant_id", "content_sha256", name="uq_dataset_content"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(20), default=DatasetKind.PRODUCTION.value)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_format: Mapped[str] = mapped_column(String(10), default="CSV")
    #: SHA-256 of the uploaded bytes together with the declared metadata.
    content_sha256: Mapped[str] = mapped_column(String(64))
    interval_minutes: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    rows_plant: Mapped[int] = mapped_column(Integer, default=0)
    rows_device: Mapped[int] = mapped_column(Integer, default=0)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Demonstration scenario key, when the dataset was produced by the generator.
    scenario_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The declarations made at import (:class:`solarwise.ingestion.schema.DatasetMetadata`).
    declared_metadata: Mapped[dict[str, Any]] = mapped_column(JSON)
    #: Channel properties in canonical form, keyed by metric.
    channels: Mapped[dict[str, Any]] = mapped_column(JSON)
    device_tag: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    validation_report: Mapped[dict[str, Any]] = mapped_column(JSON)
    #: Default assumptions shipped with a demonstration scenario (cleaning, economics).
    default_options: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ProductionObservation(Base):
    __tablename__ = "production_observations"
    __table_args__ = (
        Index("ix_production_dataset_time", "dataset_id", "start_utc"),
        UniqueConstraint("dataset_id", "device_code", "start_utc", name="uq_production_interval"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    #: Empty string for plant-level rows (keeps the uniqueness constraint effective on every backend).
    device_code: Mapped[str] = mapped_column(String(64), default="")
    start_utc: Mapped[datetime] = mapped_column(UTCDateTime)
    actual_energy_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_energy_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_irradiation_kwh_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    availability_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    curtailed_energy_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    soiling_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)


class WeatherObservation(Base):
    __tablename__ = "weather_observations"
    __table_args__ = (UniqueConstraint("dataset_id", "start_utc", name="uq_weather_interval"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    start_utc: Mapped[datetime] = mapped_column(UTCDateTime)
    poa_irradiation_kwh_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    ghi_kwh_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    ambient_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    module_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_humidity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_mm: Mapped[float | None] = mapped_column(Float, nullable=True)


class EvidenceRow(Base):
    """A documented observation: soiling test, inspection, fault, curtailment order ..."""

    __tablename__ = "evidence_records"
    __table_args__ = (Index("ix_evidence_plant_reference", "plant_id", "reference"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id", ondelete="CASCADE"), index=True)
    #: Evidence shipped with one dataset (demonstration scenarios) applies to that dataset only.
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=True)
    reference: Mapped[str] = mapped_column(String(64))
    evidence_type: Mapped[str] = mapped_column(String(40))
    observed_start: Mapped[datetime] = mapped_column(UTCDateTime)
    observed_end: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: Complete record (:class:`solarwise.core.models.EvidenceRecord`), including its provenance tag.
    record: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    weather_dataset_id: Mapped[int | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    engine_version: Mapped[str] = mapped_column(String(20))
    context: Mapped[str] = mapped_column(String(20))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    decision: Mapped[str] = mapped_column(String(20), index=True)
    rule: Mapped[str] = mapped_column(String(20))
    reason_code: Mapped[str] = mapped_column(String(60))
    diagnostic_status: Mapped[str] = mapped_column(String(40))
    simulated: Mapped[bool] = mapped_column(Boolean)
    operational_authorization: Mapped[bool] = mapped_column(Boolean)
    gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    window_gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    headline: Mapped[str] = mapped_column(Text)
    options: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)


class EconomicReference(Base):
    """A documented reference for an economic input.  Never applied automatically."""

    __tablename__ = "economic_reference_values"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    label: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(40))
    #: OFFICIAL_REFERENCE | MARKET_ESTIMATE | USER_ASSUMPTION | DEMONSTRATION_VALUE
    classification: Mapped[str] = mapped_column(String(40))
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_title: Mapped[str] = mapped_column(String(500), default="")
    source_reference: Mapped[str] = mapped_column(String(500), default="")
    #: VERIFIED | PENDING_VERIFICATION | NOT_APPLICABLE
    verification_status: Mapped[str] = mapped_column(String(40))
    applicability: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    remote_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
