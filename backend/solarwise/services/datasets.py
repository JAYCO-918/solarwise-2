"""Datasets: validation of uploads, immutable import, and loading for analysis."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from solarwise.core.data_quality import QualityIssue, Severity
from solarwise.core.models import (
    METRIC_SPECS,
    BaselineDescriptor,
    ChannelMeta,
    DeviceObservation,
    Metric,
    Observation,
)
from solarwise.core.provenance import ProvenanceTag
from solarwise.db.models import Dataset, DatasetKind, Plant, ProductionObservation, User, WeatherObservation
from solarwise.ingestion.parser import ParseError, RawTable, parse_upload
from solarwise.ingestion.schema import DatasetMetadata, unfilled_placeholders
from solarwise.ingestion.validator import IssueSeverity, ParsedDataset, ValidationReport, validate_table
from solarwise.services import plants as plant_service
from solarwise.services.errors import ConflictError, InvalidError, NotFoundError

PRODUCTION_COLUMNS: tuple[str, ...] = tuple(
    spec.column for metric, spec in METRIC_SPECS.items() if spec.table == "production" and metric is not Metric.DEVICE_ENERGY
)
WEATHER_COLUMNS: tuple[str, ...] = tuple(spec.column for spec in METRIC_SPECS.values() if spec.table == "weather")
_OBSERVATION_FIELDS = tuple(f.name for f in fields(Observation) if f.name != "start_utc")
assert set(_OBSERVATION_FIELDS) == set(PRODUCTION_COLUMNS) | set(WEATHER_COLUMNS)

_INSERT_BATCH = 5_000
#: Limits of a demonstration session.
DEMO_MAX_DATASETS = 8
DEMO_MAX_UPLOAD_MB = 5


@dataclass
class Checked:
    """Outcome of validating one upload."""

    report: ValidationReport
    parsed: ParsedDataset | None
    metadata: DatasetMetadata
    table: RawTable
    content_sha256: str
    duplicate_of: int | None


def parse_metadata(raw: str | None, table: RawTable, fallback_name: str) -> DatasetMetadata:
    """Metadata from the form field, else from the JSON envelope, else 'nothing declared'."""
    payload: Any
    if raw is not None and raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InvalidError(f"the metadata is not valid JSON: {exc.msg}", code="INVALID_METADATA") from exc
    elif table.embedded_metadata is not None:
        payload = table.embedded_metadata
    else:
        payload = {"name": fallback_name}
    if not isinstance(payload, dict):
        raise InvalidError("the metadata must be a JSON object", code="INVALID_METADATA")
    payload.setdefault("name", fallback_name)
    unfilled = unfilled_placeholders(payload)
    if unfilled:
        raise InvalidError(
            "the metadata still contains template placeholders (values starting with REPLACE): describe the data "
            "before importing them",
            code="TEMPLATE_NOT_FILLED_IN", details={"fields": unfilled[:50]},
        )
    try:
        return DatasetMetadata.model_validate(payload)
    except ValidationError as exc:
        raise InvalidError(
            "the metadata does not follow the dataset metadata schema",
            code="INVALID_METADATA",
            details=exc.errors(include_url=False, include_context=False, include_input=False),
        ) from exc


def check_upload(
    db: Session, plant: Plant, *, data: bytes, filename: str | None, content_type: str | None, metadata_json: str | None
) -> Checked:
    """Parse and validate an upload without storing anything."""
    try:
        table = parse_upload(data, filename, content_type)
    except ParseError as exc:
        raise InvalidError(str(exc), code="UNREADABLE_FILE") from exc
    fallback = (filename or "uploaded dataset").rsplit("/", 1)[-1][:200] or "uploaded dataset"
    metadata = parse_metadata(metadata_json, table, fallback)
    report, parsed = validate_table(
        table, metadata, plant=plant_service.spec_of(plant), known_devices=plant_service.device_specs(db, plant)
    )
    digest = hashlib.sha256()
    digest.update(data)
    digest.update(b"\x00")
    digest.update(json.dumps(metadata.model_dump(mode="json"), sort_keys=True).encode())
    sha = digest.hexdigest()
    duplicate = db.scalar(select(Dataset.id).where(Dataset.plant_id == plant.id, Dataset.content_sha256 == sha))
    return Checked(report=report, parsed=parsed, metadata=metadata, table=table, content_sha256=sha, duplicate_of=duplicate)


def store_parsed(
    db: Session,
    plant: Plant,
    user: User | None,
    *,
    parsed: ParsedDataset,
    report: ValidationReport,
    content_sha256: str,
    file_name: str | None,
    kind: DatasetKind = DatasetKind.PRODUCTION,
    scenario_key: str | None = None,
    default_options: dict[str, Any] | None = None,
) -> Dataset:
    """Persist a validated dataset.  Datasets are immutable once stored."""
    if report.first_local_day is None or report.last_local_day is None:
        raise InvalidError("the dataset has no usable rows")
    metadata = parsed.metadata
    dataset = Dataset(
        plant_id=plant.id,
        name=metadata.name,
        description=metadata.description,
        kind=kind.value,
        file_name=file_name,
        file_format=report.file_format,
        content_sha256=content_sha256,
        interval_minutes=parsed.interval_minutes,
        timezone=parsed.timezone,
        period_start=report.first_local_day,
        period_end=report.last_local_day,
        rows_plant=len(parsed.observations),
        rows_device=sum(len(v) for v in parsed.device_observations.values()),
        is_synthetic=metadata.is_synthetic,
        scenario_key=scenario_key,
        declared_metadata=metadata.model_dump(mode="json"),
        channels={metric.value: meta.model_dump(mode="json") for metric, meta in parsed.channels.items()},
        device_tag=parsed.device_tag.model_dump(mode="json") if parsed.device_tag is not None else None,
        validation_report=report.model_dump(mode="json"),
        default_options=default_options,
        created_by_id=user.id if user is not None else None,
    )
    db.add(dataset)
    db.flush()

    production: list[dict[str, Any]] = []
    weather: list[dict[str, Any]] = []
    for obs in parsed.observations:
        production.append(
            {"dataset_id": dataset.id, "device_code": "", "start_utc": obs.start_utc,
             **{c: getattr(obs, c) for c in PRODUCTION_COLUMNS}}
        )
        values = {c: getattr(obs, c) for c in WEATHER_COLUMNS}
        if any(v is not None for v in values.values()):
            weather.append({"dataset_id": dataset.id, "start_utc": obs.start_utc, **values})
    empty = dict.fromkeys(PRODUCTION_COLUMNS)
    for code, series in parsed.device_observations.items():
        for item in series:
            production.append(
                {**empty, "dataset_id": dataset.id, "device_code": code, "start_utc": item.start_utc,
                 "actual_energy_kwh": item.actual_energy_kwh}
            )
    for start in range(0, len(production), _INSERT_BATCH):
        db.execute(insert(ProductionObservation), production[start : start + _INSERT_BATCH])
    for start in range(0, len(weather), _INSERT_BATCH):
        db.execute(insert(WeatherObservation), weather[start : start + _INSERT_BATCH])
    return dataset


def import_upload(db: Session, plant: Plant, user: User, checked: Checked, file_name: str | None) -> Dataset:
    if checked.duplicate_of is not None:
        raise ConflictError(
            "this file, with the same declarations, has already been imported for this plant",
            code="DUPLICATE_DATASET", details={"dataset_id": checked.duplicate_of},
        )
    if checked.parsed is None or not checked.report.accepted:
        raise InvalidError(
            checked.report.summary, code="VALIDATION_FAILED", details=checked.report.model_dump(mode="json")
        )
    if user.is_demo:
        stored = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.plant_id == plant.id))
        if int(stored or 0) >= DEMO_MAX_DATASETS:
            raise ConflictError(
                f"a demonstration session may import at most {DEMO_MAX_DATASETS} datasets per plant", code="DEMO_LIMIT"
            )
    has_production = Metric.ACTUAL_ENERGY in checked.parsed.channels or bool(checked.parsed.device_observations)
    kind = DatasetKind.PRODUCTION if has_production else DatasetKind.WEATHER
    return store_parsed(
        db, plant, user, parsed=checked.parsed, report=checked.report,
        content_sha256=checked.content_sha256, file_name=file_name, kind=kind,
    )


# --------------------------------------------------------------------------- reading


def get_dataset(db: Session, user: User, dataset_id: int, *, write: bool = False) -> tuple[Dataset, Plant]:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError("dataset not found")
    try:
        plant = plant_service.get_plant(db, user, dataset.plant_id, write=write)
    except NotFoundError as exc:
        raise NotFoundError("dataset not found") from exc
    return dataset, plant


def list_datasets(db: Session, plant: Plant, *, include_archived: bool = False) -> list[Dataset]:
    query = select(Dataset).where(Dataset.plant_id == plant.id)
    if not include_archived:
        query = query.where(Dataset.archived.is_(False))
    return list(db.scalars(query.order_by(Dataset.scenario_key.is_(None), Dataset.scenario_key, Dataset.created_at.desc())))


def channels_of(dataset: Dataset) -> dict[Metric, ChannelMeta]:
    return {Metric(key): ChannelMeta.model_validate(value) for key, value in dataset.channels.items()}


def baseline_of(dataset: Dataset) -> BaselineDescriptor | None:
    raw = dataset.declared_metadata.get("baseline")
    return BaselineDescriptor.model_validate(raw) if raw is not None else None


def device_tag_of(dataset: Dataset) -> ProvenanceTag | None:
    return ProvenanceTag.model_validate(dataset.device_tag) if dataset.device_tag is not None else None


def import_issues_from(report: Mapping[str, Any]) -> list[QualityIssue]:
    """Rows and values rejected at import, taken from a validation report in its JSON form."""
    issues: list[QualityIssue] = []
    for raw in report.get("issues", []):
        if raw.get("severity") != IssueSeverity.ERROR.value:
            continue
        issues.append(
            QualityIssue(
                code=str(raw.get("code")), severity=Severity.WARNING, metric=raw.get("column"),
                message=str(raw.get("message")), count=int(raw.get("count") or 1),
            )
        )
    return issues


def import_issues_of(dataset: Dataset) -> list[QualityIssue]:
    """Rows and values rejected at import, so that every later analysis still shows them."""
    return import_issues_from(dataset.validation_report)


@dataclass
class LoadedDataset:
    observations: list[Observation]
    device_observations: dict[str, list[DeviceObservation]]


def load_observations(db: Session, dataset: Dataset) -> LoadedDataset:
    weather: dict[datetime, WeatherObservation] = {
        row.start_utc: row
        for row in db.scalars(select(WeatherObservation).where(WeatherObservation.dataset_id == dataset.id))
    }
    observations: list[Observation] = []
    devices: dict[str, list[DeviceObservation]] = {}
    seen: set[datetime] = set()
    rows = db.scalars(
        select(ProductionObservation)
        .where(ProductionObservation.dataset_id == dataset.id)
        .order_by(ProductionObservation.start_utc)
    )
    for row in rows:
        if row.device_code:
            devices.setdefault(row.device_code, []).append(
                DeviceObservation(device_code=row.device_code, start_utc=row.start_utc,
                                  actual_energy_kwh=row.actual_energy_kwh)
            )
            continue
        values: dict[str, float | None] = {c: getattr(row, c) for c in PRODUCTION_COLUMNS}
        w = weather.get(row.start_utc)
        if w is not None:
            values.update({c: getattr(w, c) for c in WEATHER_COLUMNS})
        observations.append(Observation(start_utc=row.start_utc, **values))
        seen.add(row.start_utc)
    # A weather-only dataset has no production rows at all.
    for start, w in sorted(weather.items()):
        if start not in seen:
            observations.append(Observation(start_utc=start, **{c: getattr(w, c) for c in WEATHER_COLUMNS}))
    observations.sort(key=lambda o: o.start_utc)
    return LoadedDataset(observations=observations, device_observations=devices)


def series_payload(db: Session, dataset: Dataset, *, max_points: int = 20_000) -> dict[str, Any]:
    """Plant-level time series in canonical units, column-oriented, for charts and export."""
    loaded = load_observations(db, dataset)
    observations = loaded.observations[:max_points]
    columns = [c for c in _OBSERVATION_FIELDS if any(getattr(o, c) is not None for o in observations)]
    return {
        "dataset_id": dataset.id,
        "interval_minutes": dataset.interval_minutes,
        "timezone": dataset.timezone,
        "truncated": len(loaded.observations) > max_points,
        "start_utc": [o.start_utc.isoformat() for o in observations],
        "columns": {c: [getattr(o, c) for o in observations] for c in columns},
        "units": {spec.column: spec.unit for spec in METRIC_SPECS.values() if spec.column in columns},
        "devices": sorted(loaded.device_observations),
    }
