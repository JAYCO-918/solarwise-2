"""Dataset validation.

Turns a raw table plus its declared metadata into validated observations and a
validation report.  The rules, in short:

* a value that cannot be trusted is **rejected and stored as missing** - never
  repaired, clipped or replaced by zero;
* every rejection is counted and reported with examples;
* problems that make the whole file unusable (unknown unit, no timestamp
  column, capacity mismatch ...) are ``BLOCKING`` and the import is refused;
* what the uploader did not declare (provenance, baseline properties,
  uncertainty) is reported and recorded as unknown.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from solarwise.core.models import (
    METRIC_SPECS,
    PLANT_LEVEL_METRICS,
    BaselineDescriptor,
    ChannelMeta,
    DeviceObservation,
    DeviceSpec,
    Metric,
    Observation,
    PlantSpec,
)
from solarwise.core.provenance import Provenance, ProvenanceTag
from solarwise.core.timeline import DAILY_MINUTES, SUPPORTED_INTERVALS, TimelineError, get_zone
from solarwise.core.units import UnitError, dimension_of, to_canonical
from solarwise.ingestion.parser import RawTable
from solarwise.ingestion.schema import ChannelDeclaration, DatasetMetadata

#: Cells read as "no value".
MISSING_TOKENS = frozenset({"", "na", "n/a", "nan", "null", "none", "-", "--", "#n/a", "missing"})
#: Margin above nameplate before an energy value is called inconsistent with capacity.
CAPACITY_MARGIN = 1.05
MAX_EXAMPLES = 5


class IssueSeverity(StrEnum):
    #: The dataset cannot be imported.
    BLOCKING = "BLOCKING"
    #: Values or rows were rejected (stored as missing); the rest can be imported.
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class ValidationIssue(BaseModel):
    code: str
    severity: IssueSeverity
    message: str
    column: str | None = None
    count: int = 1
    examples: list[str] = Field(default_factory=list)


class ChannelSummary(BaseModel):
    metric: Metric
    source_column: str
    canonical_column: str
    unit_in: str
    unit: str
    provenance: str
    source: str
    values: int
    missing: int
    rejected: int
    minimum: float | None
    maximum: float | None


class ValidationReport(BaseModel):
    accepted: bool
    summary: str
    dataset_name: str
    file_format: str
    rows_total: int
    rows_plant: int
    rows_device: int
    rows_rejected: int
    values_rejected: int
    interval_minutes: int | None
    timezone: str | None
    period_start: datetime | None
    period_end: datetime | None
    first_local_day: date | None
    last_local_day: date | None
    missing_intervals: int
    channels: list[ChannelSummary]
    devices: list[str]
    is_synthetic: bool
    issues: list[ValidationIssue]


@dataclass
class ParsedDataset:
    """Validated content of a dataset, ready to be stored or analysed."""

    metadata: DatasetMetadata
    interval_minutes: int
    timezone: str
    observations: list[Observation]
    device_observations: dict[str, list[DeviceObservation]]
    channels: dict[Metric, ChannelMeta]
    device_tag: ProvenanceTag | None
    baseline: BaselineDescriptor | None


class _Issues:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str | None], ValidationIssue] = {}

    def add(
        self, code: str, severity: IssueSeverity, message: str, *, column: str | None = None,
        example: str | None = None, count: int = 1,
    ) -> None:
        key = (code, column)
        issue = self._items.get(key)
        if issue is None:
            issue = ValidationIssue(code=code, severity=severity, message=message, column=column, count=0)
            self._items[key] = issue
        issue.count += count
        if example is not None and len(issue.examples) < MAX_EXAMPLES:
            issue.examples.append(example)

    @property
    def items(self) -> list[ValidationIssue]:
        order = {IssueSeverity.BLOCKING: 0, IssueSeverity.ERROR: 1, IssueSeverity.WARNING: 2, IssueSeverity.INFO: 3}
        return sorted(self._items.values(), key=lambda i: (order[i.severity], i.code))

    @property
    def blocking(self) -> bool:
        return any(i.severity is IssueSeverity.BLOCKING for i in self._items.values())


@dataclass
class _Mapped:
    metric: Metric
    source_column: str
    unit_in: str
    declaration: ChannelDeclaration
    values: int = 0
    missing: int = 0
    rejected: int = 0
    minimum: float | None = None
    maximum: float | None = None

    def seen(self, value: float) -> None:
        self.values += 1
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)


@dataclass
class _Row:
    number: int
    start_utc: datetime
    device: str | None
    values: dict[str, float | None] = field(default_factory=dict)


_DATE_FORMATS = ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y")


def parse_timestamp(raw: Any, zone: ZoneInfo) -> tuple[datetime | None, str | None]:
    """Parse one timestamp cell to an aware UTC datetime.

    Returns ``(moment, problem)``; exactly one is ``None`` except for an ambiguous
    local time, where a moment is returned together with the note ``"AMBIGUOUS"``.
    Accepted: ISO 8601 (date or date-time, with or without offset) and day-first
    ``DD/MM/YYYY[ HH:MM[:SS]]``.  Timestamps without an offset are interpreted in
    ``zone``.
    """
    if raw is None or isinstance(raw, bool | int | float):
        return None, "not a date-time text (numeric epochs are not accepted: their unit is ambiguous)"
    text = str(raw).strip()
    if not text:
        return None, "empty timestamp"
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None, "unrecognised format (use ISO 8601, e.g. 2026-05-01T13:00:00+01:00, or DD/MM/YYYY HH:MM)"
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC), None
    local = parsed.replace(tzinfo=zone)
    as_utc = local.astimezone(UTC)
    if as_utc.astimezone(zone).replace(tzinfo=None) != parsed:
        return None, f"local time does not exist in {zone.key} (daylight-saving gap)"
    if local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset():
        return as_utc, "AMBIGUOUS"
    return as_utc, None


def parse_number(raw: Any, decimal_comma: bool) -> tuple[float | None, str | None]:
    """Parse one numeric cell.  Returns ``(value, problem)``; ``(None, None)`` means missing."""
    if raw is None:
        return None, None
    if isinstance(raw, bool):
        return None, "boolean is not a number"
    if isinstance(raw, int | float):
        value = float(raw)
    else:
        text = str(raw).strip()
        if text.lower() in MISSING_TOKENS:
            return None, None
        if decimal_comma:
            text = text.replace(",", ".")
        try:
            value = float(text)
        except ValueError:
            return None, "not a number"
    if math.isnan(value):
        return None, None
    if not math.isfinite(value):
        return None, "non-finite value"
    return value, None


def validate_table(
    table: RawTable,
    metadata: DatasetMetadata,
    *,
    plant: PlantSpec,
    known_devices: Mapping[str, DeviceSpec] | None = None,
    now: datetime | None = None,
) -> tuple[ValidationReport, ParsedDataset | None]:
    """Validate ``table`` against ``metadata`` and the plant configuration."""
    issues = _Issues()
    known_devices = known_devices or {}
    now = now or datetime.now(UTC)
    columns = set(table.columns)

    def report(parsed: ParsedDataset | None, **stats: Any) -> tuple[ValidationReport, ParsedDataset | None]:
        blocking = issues.blocking
        items = issues.items
        if blocking:
            summary = "Import refused: " + "; ".join(i.code for i in items if i.severity is IssueSeverity.BLOCKING) + "."
        else:
            errors = sum(1 for i in items if i.severity is IssueSeverity.ERROR)
            warnings = sum(1 for i in items if i.severity is IssueSeverity.WARNING)
            summary = (
                f"Importable: {stats.get('rows_plant', 0)} plant-level and {stats.get('rows_device', 0)} "
                f"device-level rows; {errors} error type(s) with rejected values, {warnings} warning type(s)."
            )
        base: dict[str, Any] = {
            "rows_plant": 0, "rows_device": 0, "rows_rejected": 0, "values_rejected": 0,
            "interval_minutes": None, "timezone": None, "period_start": None, "period_end": None,
            "first_local_day": None, "last_local_day": None, "missing_intervals": 0,
            "channels": [], "devices": [],
        }
        base.update(stats)
        return (
            ValidationReport(
                accepted=not blocking,
                summary=summary,
                dataset_name=metadata.name,
                file_format=table.file_format,
                rows_total=len(table.rows),
                is_synthetic=metadata.is_synthetic,
                issues=items,
                **base,
            ),
            None if blocking else parsed,
        )

    # ------------------------------------------------------------------ time zone
    zone_name = metadata.timezone or plant.timezone
    try:
        zone = get_zone(zone_name)
    except TimelineError as exc:
        issues.add("UNKNOWN_TIMEZONE", IssueSeverity.BLOCKING, str(exc))
        return report(None)
    if metadata.timezone is None:
        issues.add("TIMEZONE_DEFAULTED", IssueSeverity.INFO,
                   f"No time zone declared: timestamps without an offset are read in the plant's zone ({zone_name}).")
    elif metadata.timezone != plant.timezone:
        issues.add("TIMEZONE_DIFFERS_FROM_PLANT", IssueSeverity.WARNING,
                   f"The dataset's time zone ({metadata.timezone}) differs from the plant's ({plant.timezone}). "
                   "Timestamps are converted; daily values must refer to the plant's local days.")

    # ------------------------------------------------------------------ columns and units
    if metadata.timestamp_column not in columns:
        issues.add("NO_TIMESTAMP_COLUMN", IssueSeverity.BLOCKING,
                   f"Column '{metadata.timestamp_column}' not found. Columns in the file: {', '.join(table.columns)}.")
        return report(None, timezone=zone_name)

    mapped: dict[Metric, _Mapped] = {}
    used_columns = {metadata.timestamp_column}
    has_device_column = metadata.device_column in columns
    if has_device_column:
        used_columns.add(metadata.device_column)
    for metric in PLANT_LEVEL_METRICS:
        spec = METRIC_SPECS[metric]
        declaration = metadata.channels.get(metric)
        source_column = (declaration.column if declaration and declaration.column else spec.column)
        if source_column not in columns:
            if declaration is not None:
                issues.add("DECLARED_COLUMN_MISSING", IssueSeverity.ERROR,
                           f"Channel '{metric.value}' is declared but its column '{source_column}' is not in the file.",
                           column=source_column)
            continue
        unit_in = declaration.unit if declaration and declaration.unit else spec.unit
        try:
            dimension = dimension_of(unit_in)
        except UnitError as exc:
            issues.add("INVALID_UNIT", IssueSeverity.BLOCKING, f"{source_column}: {exc}.", column=source_column)
            continue
        if dimension != spec.dimension:
            issues.add("INVALID_UNIT", IssueSeverity.BLOCKING,
                       f"{source_column}: unit '{unit_in}' is a unit of {dimension}, but this channel holds "
                       f"{spec.dimension} (stored in {spec.unit}).", column=source_column)
            continue
        mapped[metric] = _Mapped(metric, source_column, unit_in, declaration or ChannelDeclaration())
        used_columns.add(source_column)
        if declaration is None or declaration.provenance is Provenance.UNKNOWN:
            issues.add("PROVENANCE_NOT_DECLARED", IssueSeverity.WARNING,
                       f"No provenance declared for '{source_column}': it is recorded as UNKNOWN and cannot "
                       "serve as measured evidence.", column=source_column)
    for column in table.columns:
        if column not in used_columns:
            issues.add("UNMAPPED_COLUMN", IssueSeverity.INFO,
                       f"Column '{column}' is not mapped to any channel and is ignored.", column=column)
    if issues.blocking:
        return report(None, timezone=zone_name)
    if not mapped:
        issues.add("NO_DATA_COLUMNS", IssueSeverity.BLOCKING,
                   "No recognised data column. Use the canonical column names or map your columns in the metadata.")
        return report(None, timezone=zone_name)

    if metadata.capacity_dc_kwp is not None:
        deviation = abs(metadata.capacity_dc_kwp - plant.capacity_dc_kwp) / plant.capacity_dc_kwp
        if deviation > 0.01:
            issues.add("CAPACITY_MISMATCH", IssueSeverity.BLOCKING,
                       f"The dataset declares {metadata.capacity_dc_kwp:,.0f} kWp while the plant is configured "
                       f"with {plant.capacity_dc_kwp:,.0f} kWp. Correct the plant configuration or the metadata.")
            return report(None, timezone=zone_name)

    # ------------------------------------------------------------------ rows: timestamps and values
    rows: list[_Row] = []
    rejected_rows = 0
    values_rejected = 0
    device_metric = _Mapped(Metric.DEVICE_ENERGY, METRIC_SPECS[Metric.ACTUAL_ENERGY].column, "kWh", ChannelDeclaration())
    actual = mapped.get(Metric.ACTUAL_ENERGY)
    if actual is not None:
        device_metric.source_column, device_metric.unit_in = actual.source_column, actual.unit_in
    unknown_devices: Counter[str] = Counter()

    for number, raw in enumerate(table.rows, start=2 if table.file_format == "CSV" else 1):
        moment, problem = parse_timestamp(raw.get(metadata.timestamp_column), zone)
        if moment is None:
            rejected_rows += 1
            issues.add("INVALID_TIMESTAMP", IssueSeverity.ERROR, "Rows with an unusable timestamp were rejected.",
                       column=metadata.timestamp_column,
                       example=f"row {number}: '{raw.get(metadata.timestamp_column)}' - {problem}")
            continue
        if problem == "AMBIGUOUS":
            issues.add("AMBIGUOUS_LOCAL_TIME", IssueSeverity.WARNING,
                       "Local times that occur twice (end of daylight saving) were read as the first occurrence. "
                       "Supply UTC offsets to remove the ambiguity.", example=f"row {number}")
        if moment > now + timedelta(days=1):
            issues.add("FUTURE_TIMESTAMP", IssueSeverity.WARNING, "Timestamps lie in the future.",
                       example=f"row {number}: {moment.isoformat()}")
        device: str | None = None
        if has_device_column:
            cell = raw.get(metadata.device_column)
            text = "" if cell is None else str(cell).strip()
            device = text or None
        row = _Row(number=number, start_utc=moment, device=device)

        targets = [device_metric] if device is not None else list(mapped.values())
        for channel in targets:
            spec = METRIC_SPECS[channel.metric]
            value, problem = parse_number(raw.get(channel.source_column), table.decimal_comma)
            if problem is not None:
                channel.rejected += 1
                values_rejected += 1
                issues.add("NON_NUMERIC" if problem == "not a number" else "NON_FINITE", IssueSeverity.ERROR,
                           "Cells that are not finite numbers were rejected and stored as missing.",
                           column=channel.source_column,
                           example=f"row {number}: '{raw.get(channel.source_column)}'")
                row.values[spec.column] = None
                continue
            if value is None:
                channel.missing += 1
                row.values[spec.column] = None
                continue
            converted = to_canonical(value, channel.unit_in, expected_dimension=spec.dimension)
            if channel.metric is Metric.RELATIVE_HUMIDITY:
                converted *= 100.0  # stored in percent
            if spec.minimum is not None and converted < spec.minimum:
                channel.rejected += 1
                values_rejected += 1
                negative = converted < 0
                issues.add(
                    "NEGATIVE_VALUE" if negative else "OUT_OF_RANGE", IssueSeverity.ERROR,
                    (f"Negative values of '{channel.source_column}' are physically impossible; they were rejected "
                     "and stored as missing (not as zero)." if negative else
                     f"Values of '{channel.source_column}' below {spec.minimum:g} {spec.unit} were rejected and stored as missing."),
                    column=channel.source_column, example=f"row {number}: {value:g}",
                )
                row.values[spec.column] = None
                continue
            if spec.maximum is not None and converted > spec.maximum:
                channel.rejected += 1
                values_rejected += 1
                issues.add("OUT_OF_RANGE", IssueSeverity.ERROR,
                           f"Values of '{channel.source_column}' above {spec.maximum:g} {spec.unit} are outside the "
                           "valid range of the sensor; they were rejected and stored as missing.",
                           column=channel.source_column, example=f"row {number}: {value:g}")
                row.values[spec.column] = None
                continue
            channel.seen(converted)
            row.values[spec.column] = converted
        if device is not None and device not in known_devices:
            unknown_devices[device] += 1
            continue
        rows.append(row)

    for code, count in unknown_devices.items():
        issues.add("UNKNOWN_DEVICE", IssueSeverity.WARNING,
                   "Rows refer to device codes that are not registered for this plant; they were ignored. "
                   "Register the devices first.", example=f"{code} ({count} rows)", count=count)

    plant_rows = [r for r in rows if r.device is None]
    device_rows = [r for r in rows if r.device is not None]
    if not rows:
        issues.add("NO_USABLE_DATA", IssueSeverity.BLOCKING, "No row could be used.")
        return report(None, timezone=zone_name, rows_rejected=rejected_rows, values_rejected=values_rejected)

    # ------------------------------------------------------------------ interval
    groups: dict[str | None, list[datetime]] = {}
    for r in rows:
        groups.setdefault(r.device, []).append(r.start_utc)
    longest = groups[None] if None in groups else max(groups.values(), key=lambda g: len(g))
    reference = sorted(set(longest))
    diffs = Counter(int((b - a).total_seconds() // 60) for a, b in itertools.pairwise(reference))
    inferred = diffs.most_common(1)[0][0] if diffs else None
    # Daily data across a daylight-saving change has 23 h or 25 h steps.
    if inferred in (DAILY_MINUTES - 60, DAILY_MINUTES + 60):
        inferred = DAILY_MINUTES
    interval = metadata.interval_minutes or inferred
    if interval is None:
        issues.add("INTERVAL_UNKNOWN", IssueSeverity.BLOCKING,
                   "The interval cannot be inferred from a single timestamp; declare 'interval_minutes'.")
        return report(None, timezone=zone_name, rows_rejected=rejected_rows, values_rejected=values_rejected)
    if interval not in SUPPORTED_INTERVALS:
        issues.add("UNSUPPORTED_INTERVAL", IssueSeverity.BLOCKING,
                   f"The data are spaced {interval} minutes apart; supported intervals are 15, 30, 60 minutes and 1 day.")
        return report(None, timezone=zone_name, rows_rejected=rejected_rows, values_rejected=values_rejected)
    if metadata.interval_minutes is not None and inferred is not None and inferred != metadata.interval_minutes:
        issues.add("INTERVAL_MISMATCH", IssueSeverity.BLOCKING,
                   f"The metadata declares {metadata.interval_minutes}-minute intervals but the timestamps are mostly "
                   f"{inferred} minutes apart.")
        return report(None, timezone=zone_name, rows_rejected=rejected_rows, values_rejected=values_rejected)

    # ------------------------------------------------------------------ alignment
    aligned: list[_Row] = []
    for r in rows:
        local = r.start_utc.astimezone(zone)
        if interval == DAILY_MINUTES:
            on_grid = local.time() == time.min
        else:
            on_grid = local.second == 0 and local.microsecond == 0 and (local.hour * 60 + local.minute) % interval == 0
        if on_grid:
            aligned.append(r)
        else:
            rejected_rows += 1
            issues.add("MISALIGNED_TIMESTAMP", IssueSeverity.ERROR,
                       ("Daily rows must start at local midnight; other rows were rejected." if interval == DAILY_MINUTES
                        else f"Rows whose start is not on the {interval}-minute grid were rejected."),
                       column=metadata.timestamp_column, example=f"row {r.number}: {local.isoformat()}")

    # ------------------------------------------------------------------ duplicates
    by_key: dict[tuple[str | None, datetime], list[_Row]] = {}
    for r in aligned:
        by_key.setdefault((r.device, r.start_utc), []).append(r)
    unique: list[_Row] = []
    for (_device, moment), group in by_key.items():
        if len(group) == 1:
            unique.append(group[0])
            continue
        if all(g.values == group[0].values for g in group[1:]):
            unique.append(group[0])
            issues.add("DUPLICATE_ROWS", IssueSeverity.WARNING,
                       "Identical duplicate rows were found; one copy was kept.",
                       example=f"rows {', '.join(str(g.number) for g in group)} ({moment.astimezone(zone).isoformat()})",
                       count=len(group) - 1)
        else:
            rejected_rows += len(group)
            issues.add("CONFLICTING_DUPLICATES", IssueSeverity.ERROR,
                       "Several rows share a timestamp but disagree. None was kept: SolarWise does not choose "
                       "between conflicting values.",
                       example=f"rows {', '.join(str(g.number) for g in group)} ({moment.astimezone(zone).isoformat()})",
                       count=len(group))
    unique.sort(key=lambda r: (r.device or "", r.start_utc))
    plant_rows = [r for r in unique if r.device is None]
    device_rows = [r for r in unique if r.device is not None]

    # ------------------------------------------------------------------ capacity consistency
    hours = 24.0 if interval == DAILY_MINUTES else interval / 60.0
    plant_capacity = plant.capacity_ac_kw if plant.capacity_ac_kw is not None else plant.capacity_dc_kwp
    limit = plant_capacity * hours * CAPACITY_MARGIN
    energy_values = [r.values.get("actual_energy_kwh") for r in plant_rows]
    present = [v for v in energy_values if v is not None]
    exceeding = [r for r in plant_rows if (r.values.get("actual_energy_kwh") or 0.0) > limit]
    if exceeding:
        share = len(exceeding) / max(1, len(present))
        severity = IssueSeverity.BLOCKING if share > 0.5 else IssueSeverity.ERROR
        issues.add("ENERGY_EXCEEDS_CAPACITY", severity,
                   f"Actual energy exceeds what the configured capacity ({plant_capacity:,.0f} kW) can deliver in "
                   f"one interval ({limit:,.0f} kWh) in {len(exceeding)} row(s)"
                   + (": the energy unit or the plant capacity is inconsistent with the data."
                      if severity is IssueSeverity.BLOCKING else ". The values are kept and flagged."),
                   column=actual.source_column if actual else None,
                   example=f"row {exceeding[0].number}: {exceeding[0].values['actual_energy_kwh']:,.0f} kWh",
                   count=len(exceeding))
    expected_over = [r for r in plant_rows if (r.values.get("expected_energy_kwh") or 0.0) > limit]
    if expected_over:
        issues.add("EXPECTED_EXCEEDS_CAPACITY", IssueSeverity.WARNING,
                   f"Expected energy exceeds the capacity-limited maximum in {len(expected_over)} row(s): the "
                   "baseline may refer to a different capacity.", count=len(expected_over))
    for r in device_rows:
        assert r.device is not None
        capacity = known_devices[r.device].capacity_kwp
        if (r.values.get("actual_energy_kwh") or 0.0) > capacity * hours * CAPACITY_MARGIN:
            issues.add("DEVICE_ENERGY_EXCEEDS_CAPACITY", IssueSeverity.ERROR,
                       "Device energy exceeds what the registered device capacity can deliver; values are kept and flagged.",
                       example=f"row {r.number}: {r.device}")
    if present and all(v == 0.0 for v in present):
        issues.add("ALL_ZERO_PRODUCTION", IssueSeverity.WARNING, "Every actual-energy value is zero.")

    # ------------------------------------------------------------------ declarations worth flagging
    if Metric.EXPECTED_ENERGY in mapped and metadata.baseline is None:
        issues.add("BASELINE_NOT_DESCRIBED", IssueSeverity.WARNING,
                   "The file contains expected energy but the metadata does not describe the baseline "
                   "(method, whether it is adjusted for actual irradiance and temperature). It is treated as "
                   "'method unknown, adjustments not declared'.")
    if Metric.SOILING_RATIO in mapped and mapped[Metric.SOILING_RATIO].declaration.soiling_method is None:
        issues.add("SOILING_METHOD_NOT_DECLARED", IssueSeverity.WARNING,
                   "The soiling-ratio channel does not state how it is obtained (soiling station, reference "
                   "module ...). Without a direct method it cannot serve as credible soiling evidence.")
    for metric in (Metric.ACTUAL_ENERGY, Metric.EXPECTED_ENERGY):
        if metric in mapped and mapped[metric].declaration.uncertainty_pct is None:
            issues.add("UNCERTAINTY_NOT_DECLARED", IssueSeverity.INFO,
                       "No measurement/model uncertainty declared for an energy channel: the gap can only be "
                       "judged against the materiality threshold.", column=mapped[metric].source_column)
        if metric in mapped and mapped[metric].declaration.boundary is None:
            issues.add("METERING_BOUNDARY_NOT_DECLARED", IssueSeverity.INFO,
                       "Metering boundary not declared for an energy channel.", column=mapped[metric].source_column)
    if metadata.is_synthetic:
        issues.add("SYNTHETIC_DATASET", IssueSeverity.INFO,
                   "The dataset is declared synthetic. It can illustrate the method; it can never support an "
                   "operational cleaning decision.")

    if issues.blocking:
        return report(None, timezone=zone_name, rows_rejected=rejected_rows, values_rejected=values_rejected,
                      interval_minutes=interval)
    if not plant_rows and not device_rows:
        issues.add("NO_USABLE_DATA", IssueSeverity.BLOCKING, "No row could be used.")
        return report(None, timezone=zone_name, rows_rejected=rejected_rows, values_rejected=values_rejected)

    # ------------------------------------------------------------------ build observations
    observations = [Observation(start_utc=r.start_utc, **r.values) for r in plant_rows]
    device_observations: dict[str, list[DeviceObservation]] = {}
    for r in device_rows:
        assert r.device is not None
        device_observations.setdefault(r.device, []).append(
            DeviceObservation(device_code=r.device, start_utc=r.start_utc,
                              actual_energy_kwh=r.values.get("actual_energy_kwh"))
        )

    all_starts = [r.start_utc for r in unique]
    first, last = min(all_starts), max(all_starts)
    missing_intervals = 0
    if plant_rows:
        p_first, p_last = plant_rows[0].start_utc, plant_rows[-1].start_utc
        if interval == DAILY_MINUTES:
            span = (p_last.astimezone(zone).date() - p_first.astimezone(zone).date()).days + 1
        else:
            span = int((p_last - p_first).total_seconds() // (interval * 60)) + 1
        missing_intervals = max(0, span - len(plant_rows))
        if missing_intervals:
            issues.add("TIME_GAPS", IssueSeverity.INFO,
                       f"{missing_intervals} interval(s) between the first and last timestamp have no row. "
                       "They remain missing; nothing is interpolated.", count=missing_intervals)

    channels = {metric: m.declaration.to_meta(metric) for metric, m in mapped.items() if m.values > 0}
    empty = [m.source_column for m in mapped.values() if m.values == 0]
    for column in empty:
        issues.add("EMPTY_CHANNEL", IssueSeverity.WARNING,
                   f"Column '{column}' contains no usable value.", column=column)
    device_tag: ProvenanceTag | None = None
    if device_observations:
        device_tag = (actual.declaration if actual else ChannelDeclaration()).tag()

    summaries = [
        ChannelSummary(
            metric=m.metric, source_column=m.source_column, canonical_column=METRIC_SPECS[m.metric].column,
            unit_in=m.unit_in, unit=METRIC_SPECS[m.metric].unit, provenance=m.declaration.tag().label,
            source=m.declaration.tag().source, values=m.values, missing=m.missing, rejected=m.rejected,
            minimum=m.minimum, maximum=m.maximum,
        )
        for m in mapped.values()
    ]
    if device_observations:
        summaries.append(
            ChannelSummary(
                metric=Metric.DEVICE_ENERGY, source_column=device_metric.source_column,
                canonical_column="actual_energy_kwh", unit_in=device_metric.unit_in, unit="kWh",
                provenance=device_tag.label if device_tag else "UNKNOWN",
                source=device_tag.source if device_tag else "", values=device_metric.values,
                missing=device_metric.missing, rejected=device_metric.rejected,
                minimum=device_metric.minimum, maximum=device_metric.maximum,
            )
        )

    parsed = ParsedDataset(
        metadata=metadata,
        interval_minutes=interval,
        timezone=zone_name,
        observations=observations,
        device_observations=device_observations,
        channels=channels,
        device_tag=device_tag,
        baseline=metadata.baseline if Metric.EXPECTED_ENERGY in channels else None,
    )
    return report(
        parsed,
        rows_plant=len(plant_rows),
        rows_device=len(device_rows),
        rows_rejected=rejected_rows,
        values_rejected=values_rejected,
        interval_minutes=interval,
        timezone=zone_name,
        period_start=first,
        period_end=last,
        first_local_day=first.astimezone(zone).date(),
        last_local_day=last.astimezone(zone).date(),
        missing_intervals=missing_intervals,
        channels=summaries,
        devices=sorted(device_observations),
    )
