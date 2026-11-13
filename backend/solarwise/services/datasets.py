"""Datasets: preview and validation of uploads, immutable import, and loading for analysis."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import date, datetime
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
    EvidenceRecord,
    Metric,
    Observation,
)
from solarwise.core.provenance import Provenance, ProvenanceTag
from solarwise.db.models import (
    Dataset,
    DatasetFile,
    DatasetKind,
    EvidenceRow,
    Plant,
    ProductionObservation,
    User,
    WeatherObservation,
)
from solarwise.ingestion.detect import UploadPreview, preview_table
from solarwise.ingestion.parser import ParseError, RawTable, parse_upload
from solarwise.ingestion.schema import DatasetMetadata, unfilled_placeholders
from solarwise.ingestion.validator import IssueSeverity, ParsedDataset, Rejection, ValidationReport, validate_table
from solarwise.services import evidence as evidence_service
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
class Overlap:
    """A dataset of the plant that covers some of the same days."""

    dataset_id: int
    name: str
    period_start: date
    period_end: date


@dataclass
class Checked:
    """Outcome of validating one upload."""

    report: ValidationReport
    parsed: ParsedDataset | None
    metadata: DatasetMetadata
    table: RawTable
    content_sha256: str
    duplicate_of: int | None
    #: The uploaded bytes, their fingerprint, and what the browser said about the file.
    data: bytes = b""
    file_sha256: str = ""
    content_type: str = ""
    #: Datasets of the plant imported from the very same file, under whatever declaration.
    same_file_as: list[int] = field(default_factory=list)
    #: Datasets of the plant that cover some of the same days.
    overlapping: list[Overlap] = field(default_factory=list)
    #: Every rejected cell and row (only collected on request).
    rejections: list[Rejection] = field(default_factory=list)


def fingerprint(data: bytes, metadata: DatasetMetadata) -> str:
    """SHA-256 of the uploaded bytes together with what was declared about them.

    Declarations that use none of the fields added after the first release hash exactly as they always did, so that
    a file imported then is still recognised as a duplicate now.
    """
    declared = metadata.model_dump(mode="json")
    if declared.get("events") is None:
        declared.pop("events", None)
    for channel in declared.get("channels", {}).values():
        if channel.get("reported_as") != "LOSS":  # a ratio, stated or not, is what a channel always was
            channel.pop("reported_as", None)
    digest = hashlib.sha256()
    digest.update(data)
    digest.update(b"\x00")
    digest.update(json.dumps(declared, sort_keys=True).encode())
    return digest.hexdigest()


def _same_file(db: Session, plant: Plant, file_sha256: str) -> list[int]:
    return list(
        db.scalars(
            select(Dataset.id).join(DatasetFile, DatasetFile.dataset_id == Dataset.id)
            .where(Dataset.plant_id == plant.id, DatasetFile.sha256 == file_sha256).order_by(Dataset.id)
        )
    )


def _read(data: bytes, filename: str | None, content_type: str | None) -> RawTable:
    try:
        return parse_upload(data, filename, content_type)
    except ParseError as exc:
        raise InvalidError(str(exc), code="UNREADABLE_FILE") from exc


def preview_upload(
    db: Session, plant: Plant, *, data: bytes, filename: str | None, content_type: str | None
) -> tuple[UploadPreview, str, list[int]]:
    """What the file contains and what its columns probably are.  Nothing is validated or stored."""
    table = _read(data, filename, content_type)
    preview = preview_table(table, plant=plant_service.spec_of(plant), known_devices=plant_service.device_specs(db, plant))
    file_sha256 = hashlib.sha256(data).hexdigest()
    return preview, file_sha256, _same_file(db, plant, file_sha256)


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
    db: Session, plant: Plant, *, data: bytes, filename: str | None, content_type: str | None, metadata_json: str | None,
    collect_rejections: bool = False,
) -> Checked:
    """Parse and validate an upload without storing anything."""
    table = _read(data, filename, content_type)
    fallback = (filename or "uploaded dataset").rsplit("/", 1)[-1][:200] or "uploaded dataset"
    metadata = parse_metadata(metadata_json, table, fallback)
    rejections: list[Rejection] = []
    report, parsed = validate_table(
        table, metadata, plant=plant_service.spec_of(plant), known_devices=plant_service.device_specs(db, plant),
        rejections=rejections if collect_rejections else None,
    )
    sha = fingerprint(data, metadata)
    duplicate = db.scalar(select(Dataset.id).where(Dataset.plant_id == plant.id, Dataset.content_sha256 == sha))
    file_sha256 = hashlib.sha256(data).hexdigest()
    overlapping: list[Overlap] = []
    if report.first_local_day is not None and report.last_local_day is not None and report.rows_plant > 0:
        has_production = any(c.metric is Metric.ACTUAL_ENERGY for c in report.channels)
        kind = DatasetKind.PRODUCTION if has_production else DatasetKind.WEATHER
        overlapping = [
            Overlap(dataset_id=d.id, name=d.name, period_start=d.period_start, period_end=d.period_end)
            for d in db.scalars(
                select(Dataset).where(
                    Dataset.plant_id == plant.id, Dataset.archived.is_(False), Dataset.kind == kind.value,
                    Dataset.period_start <= report.last_local_day, Dataset.period_end >= report.first_local_day,
                ).order_by(Dataset.id)
            )
            if d.id != duplicate
        ]
    return Checked(
        report=report, parsed=parsed, metadata=metadata, table=table, content_sha256=sha, duplicate_of=duplicate,
        data=data, file_sha256=file_sha256, content_type=(content_type or "")[:100],
        same_file_as=[i for i in _same_file(db, plant, file_sha256) if i != duplicate],
        overlapping=overlapping, rejections=rejections,
    )


#: Cells a spreadsheet would run as a formula.  A leading plus or minus is left alone: those are numbers.
_FORMULA_START = ("=", "@", "\t", "\r")


def _safe_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def rejected_rows_csv(table: RawTable, rejections: list[Rejection], total: int | None = None) -> str:
    """The rows of the file that had something rejected, as they are in the file, with the reason next to each.

    ``solarwise_row`` is the row number quoted in the validation report; ``solarwise_problems`` lists what was
    rejected on that row.  Everything else is the uploader's own row, so that it can be corrected and sent again.
    When the file has more rejections than are listed (``total``), a last line says how many are not.
    """
    offset = 2 if table.file_format == "CSV" else 1
    by_row: dict[int, list[Rejection]] = {}
    for rejection in rejections:
        by_row.setdefault(rejection.row, []).append(rejection)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["solarwise_row", *(_safe_cell(c) for c in table.columns), "solarwise_problems"])
    for number in sorted(by_row):
        index = number - offset
        row = table.rows[index] if 0 <= index < len(table.rows) else {}
        problems = " | ".join(
            (f"{r.column}: " if r.column else "") + f"{r.problem} [{r.code}]" for r in by_row[number]
        )
        writer.writerow([number, *(_safe_cell(row.get(c)) for c in table.columns), _safe_cell(problems)])
    if total is not None and total > len(rejections):
        writer.writerow([
            "", *("" for _ in table.columns),
            f"{total - len(rejections):,} further rejected cells or rows are not listed: the list stops at "
            f"{len(rejections):,}. The validation report counts them all.",
        ])
    return out.getvalue()


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


def _event_record(record: EvidenceRecord, user: User) -> EvidenceRecord:
    """Nothing uploaded in a demonstration session is a real observation of a real plant."""
    tag = record.tag
    if not user.is_demo or tag.provenance is Provenance.SYNTHETIC:
        return record
    emulates = tag.provenance if tag.provenance in (Provenance.MEASURED, Provenance.MODELLED) else None
    return record.model_copy(
        update={"tag": ProvenanceTag(provenance=Provenance.SYNTHETIC, emulates=emulates, source=tag.source, method=tag.method)}
    )


def import_upload(db: Session, plant: Plant, user: User, checked: Checked, file_name: str | None) -> Dataset:
    """Store a validated upload: the values, the declarations, the file itself and the events it carries."""
    dataset = _import(db, plant, user, checked, file_name)
    if checked.data:
        rejected = (
            rejected_rows_csv(checked.table, checked.rejections, checked.report.rejections_total)
            if checked.rejections else None
        )
        db.add(
            DatasetFile(
                dataset_id=dataset.id, file_name=(file_name or "")[:255], content_type=checked.content_type,
                size_bytes=len(checked.data), sha256=checked.file_sha256, encoding="zlib",
                content=zlib.compress(checked.data, 6),
                rejected_rows=zlib.compress(rejected.encode("utf-8"), 6) if rejected is not None else None,
                rejections=len(checked.rejections),
            )
        )
    if checked.parsed is not None:
        for record in checked.parsed.events:
            evidence_service.add_evidence(db, plant, user, _event_record(record, user), dataset)
    db.flush()
    return dataset


def original_file(db: Session, dataset: Dataset) -> tuple[DatasetFile, bytes] | None:
    """The file the dataset was imported from, byte for byte; ``None`` for a dataset that did not come from an upload."""
    stored = db.get(DatasetFile, dataset.id)
    if stored is None:
        return None
    data = zlib.decompress(stored.content) if stored.encoding == "zlib" else bytes(stored.content)
    return stored, data


def stored_rejected_rows(db: Session, dataset: Dataset) -> str | None:
    """The rows rejected when the dataset was imported, as CSV; ``None`` when nothing was rejected or kept."""
    stored = db.get(DatasetFile, dataset.id)
    if stored is None or stored.rejected_rows is None:
        return None
    return zlib.decompress(stored.rejected_rows).decode("utf-8")


def events_of(db: Session, dataset: Dataset) -> list[EvidenceRow]:
    """Evidence records that came with the dataset (events of the file, or of a demonstration scenario)."""
    return list(
        db.scalars(select(EvidenceRow).where(EvidenceRow.dataset_id == dataset.id).order_by(EvidenceRow.observed_start))
    )


def _import(db: Session, plant: Plant, user: User, checked: Checked, file_name: str | None) -> Dataset:
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
