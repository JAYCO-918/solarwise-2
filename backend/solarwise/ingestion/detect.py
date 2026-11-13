"""Reading a file before anything has been declared about it.

An operator's export rarely uses the canonical column names.  This module looks
at the header and at the values and *proposes* what each column is, in which
unit, and what looks odd.  Three rules hold throughout:

* everything here is a proposal - nothing is applied until the uploader has
  seen it and confirmed it, and the validator then judges the file exactly as
  it would judge a hand-written declaration;
* a proposal never includes a provenance: where a column comes from cannot be
  read from a file, so it stays ``UNKNOWN`` until the uploader declares it;
* nothing is repaired - a suspicious unit or pattern is reported as a note, the
  values are left as they are.

The logic is deterministic: fixed vocabularies and fixed thresholds, no model.
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from solarwise.core.models import METRIC_SPECS, PLANT_LEVEL_METRICS, DeviceSpec, Metric, PlantSpec
from solarwise.core.timeline import DAILY_MINUTES, SUPPORTED_INTERVALS, TimelineError, get_zone
from solarwise.core.units import UnitError, dimension_of
from solarwise.core.units import accepted_units as units_by_dimension
from solarwise.ingestion.parser import RawTable
from solarwise.ingestion.schema import DEFAULT_DEVICE_COLUMN, DEFAULT_TIMESTAMP_COLUMN
from solarwise.ingestion.validator import (
    CAPACITY_MARGIN,
    CLEANING_TOKENS,
    MAX_IRRADIANCE_W_M2,
    MISSING_TOKENS,
    NO_EVENT_TOKENS,
    parse_number,
    parse_timestamp,
)

#: Rows shown to the uploader.
PREVIEW_ROWS = 12
#: Distinct values quoted per column.
SAMPLE_VALUES = 5
#: Rows read to describe the timestamps (the interval of a regular file shows within the first rows).
TIMESTAMP_SCAN = 5_000


class ColumnRole(StrEnum):
    TIMESTAMP = "TIMESTAMP"
    DEVICE = "DEVICE"
    QUANTITY = "QUANTITY"
    CLEANING = "CLEANING"
    EVENTS = "EVENTS"
    UNUSED = "UNUSED"


class Confidence(StrEnum):
    #: The column carries the canonical name.
    EXACT = "EXACT"
    #: The header names the quantity.
    NAME = "NAME"
    #: The header fits, but could mean something else: the uploader has to look.
    AMBIGUOUS = "AMBIGUOUS"
    NONE = "NONE"


class ColumnPreview(BaseModel):
    name: str
    role: ColumnRole
    metric: Metric | None = None
    #: Unit proposed for the mapping (a symbol the validator accepts).
    unit: str | None = None
    #: ``HEADER`` when the header states the unit, ``ASSUMED`` when the canonical unit was taken for want of one.
    unit_source: Literal["HEADER", "ASSUMED"] | None = None
    #: Soiling column only: the header speaks of a loss, not of a ratio.
    reported_as: Literal["RATIO", "LOSS"] | None = None
    confidence: Confidence = Confidence.NONE
    reason: str = ""
    filled: int = 0
    empty: int = 0
    numeric: int = 0
    minimum: float | None = None
    maximum: float | None = None
    samples: list[str] = Field(default_factory=list)


class DataNote(BaseModel):
    """Something about the file the uploader should look at before importing it."""

    code: str
    severity: Literal["WARNING", "INFO"]
    column: str | None = None
    message: str
    #: A unit that would address the note, when there is an obvious one.  Offered, never applied.
    suggested_unit: str | None = None


class ChannelProposal(BaseModel):
    column: str
    unit: str
    reported_as: Literal["RATIO", "LOSS"] = "RATIO"


class MappingProposal(BaseModel):
    timestamp_column: str | None = None
    device_column: str | None = None
    cleaning_column: str | None = None
    event_column: str | None = None
    #: Interval read from the timestamps, when they are regular.
    interval_minutes: int | None = None
    #: metric -> proposed column and unit.
    channels: dict[Metric, ChannelProposal] = Field(default_factory=dict)


class UploadPreview(BaseModel):
    """What a file contains and what its columns probably are.  Nothing has been stored or declared."""

    file_format: str
    rows_total: int
    columns: list[ColumnPreview]
    #: The first rows, cell by cell, exactly as they are in the file.
    sample_rows: list[list[str]]
    proposal: MappingProposal
    notes: list[DataNote]
    #: The JSON file carries its own declaration (``metadata``).
    embedded_metadata: bool
    decimal_comma: bool


# --------------------------------------------------------------------------- headers

_UNIT_IN_BRACKETS = re.compile(r"[(\[{]\s*([^)\]}]{1,16})\s*[)\]}]")

#: Header spelling of a unit -> symbol understood by :mod:`solarwise.core.units`.
_HEADER_UNITS: dict[str, str] = {
    "kwh": "kWh", "mwh": "mwh", "wh": "wh", "gwh": "gwh",
    "kwh/m2": "kWh/m2", "kwhm2": "kWh/m2", "kwh m2": "kWh/m2", "kwh/m^2": "kWh/m2",
    "wh/m2": "wh/m2", "whm2": "wh/m2", "wh m2": "wh/m2", "mj/m2": "mj/m2", "mjm2": "mj/m2", "mj m2": "mj/m2",
    "w/m2": "w/m2", "wm2": "w/m2", "w m2": "w/m2", "w/m^2": "w/m2", "w m-2": "w/m2", "kw/m2": "kw/m2",
    "degc": "degC", "c": "degC", "celsius": "degC", "deg c": "degC", "oc": "degC",
    "k": "k", "kelvin": "k", "degf": "degf", "f": "degf", "fahrenheit": "degf",
    "%": "percent", "pct": "percent", "percent": "percent", "pourcent": "percent", "pc": "percent",
    "fraction": "fraction", "ratio": "fraction", "0-1": "fraction",
    "m/s": "m/s", "ms": "m/s", "m s": "m/s", "mps": "m/s", "m s-1": "m/s", "km/h": "km/h", "kmh": "km/h", "kph": "km/h",
    "mm": "mm", "cm": "cm",
    # Power is not a quantity SolarWise stores: recognised so that a power column is not taken for energy.
    "kw": "kw", "mw": "mw", "w": "w", "kwp": "kwp",
}
#: Unit words that may end a header without brackets (``energy_kwh``, ``irradiance w/m2``).  Longest first.
_TRAILING_UNITS = sorted(
    (u for u in _HEADER_UNITS if u not in ("c", "f", "k", "w", "ms", "m s", "pc", "oc", "ratio", "fraction", "0-1", "cm")),
    key=len, reverse=True,
)


def _fold(text: str) -> str:
    """Lower case, accents removed, degree and square signs spelt out."""
    text = text.replace("²", "2").replace("°", "deg").replace("º", "deg")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def split_header(header: str) -> tuple[str, str | None]:
    """``("energy", "mwh")`` for ``"Energy (MWh)"``: the name in plain words, and the unit the header states."""
    folded = _fold(header)
    unit: str | None = None
    bracket = _UNIT_IN_BRACKETS.search(folded)
    if bracket is not None:
        candidate = " ".join(bracket.group(1).replace("_", " ").split())
        symbol = _HEADER_UNITS.get(candidate) or _HEADER_UNITS.get(candidate.replace(" ", ""))
        if symbol is not None:
            unit = symbol
            folded = folded[: bracket.start()] + " " + folded[bracket.end():]
    if unit is None and "%" in folded:
        unit = "percent"
        folded = folded.replace("%", " ")
    words = " ".join(re.sub(r"[^a-z0-9/^-]+", " ", folded).split())
    if unit is None:
        for candidate in _TRAILING_UNITS:
            spelt = candidate.replace("/", " ").replace("^", "")
            for form in {candidate, spelt, spelt.replace(" ", "")}:
                if words == form:
                    continue  # a header that is nothing but a unit names no quantity
                if words.endswith(" " + form):
                    unit = _HEADER_UNITS[candidate]
                    words = words[: -len(form)].strip()
                    break
            if unit is not None:
                break
    if unit is None:
        # A single letter is a unit only after a word that calls for it: "temp_c", "tmod c", "wind ms".
        short = re.match(r"^(.*(?:temp\w*|^t ?(?:mod|amb|cell)|ambient|ambiante|module|panel|cell)) (c|f|k)$", words)
        if short is not None:
            words, unit = short.group(1), {"c": "degC", "f": "degf", "k": "k"}[short.group(2)]
        elif re.match(r"^.*(?:wind|vent).* ms$", words):
            words, unit = words[:-3], "m/s"
    name = " ".join(re.sub(r"[^a-z0-9]+", " ", words).split())
    return name, unit


@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    role: ColumnRole
    metric: Metric | None
    confidence: Confidence
    reason: str
    reported_as: Literal["RATIO", "LOSS"] | None = None


def _rule(pattern: str, role: ColumnRole, metric: Metric | None, confidence: Confidence, reason: str,
          reported_as: Literal["RATIO", "LOSS"] | None = None) -> _Rule:
    return _Rule(re.compile(pattern), role, metric, confidence, reason, reported_as)


_Q = ColumnRole.QUANTITY
_N, _A = Confidence.NAME, Confidence.AMBIGUOUS
_ENERGY_WORD = r"(?:energy|energie|production|generation|output|yield)"
_EXPECTED_WORD = (
    r"(?:expected|reference|baseline|budget|theoretical|theorique|attendue?|prevue?|target|modell?ed|simulated|"
    r"forecast|predicted)"
)

#: Evaluated in order; the first rule whose pattern is found in the plain-word name decides.
_RULES: tuple[_Rule, ...] = (
    _rule(r"^(?:timestamp|time ?stamp|date ?time|date time|date|time|day|jour|horodatage|date heure|heure|"
          r"period(?: start)?|interval(?: start)?|start(?: time)?|ts|utc(?: time)?|local time)$",
          ColumnRole.TIMESTAMP, None, _N, "the header names a date or a time"),
    _rule(r"^(?:device(?: code| id| name)?|inverter(?: code| id| name| no)?|onduleur|equipment(?: id| code)?|"
          r"unit(?: id| code)?|block(?: id| code)?)$",
          ColumnRole.DEVICE, None, _N, "the header names a device"),
    _rule(r"^(?:cleaning(?: event| events| done| flag)?|cleaned|nettoyage|wash(?:ing|ed)?|lavage)$",
          ColumnRole.CLEANING, None, _N, "the header names cleaning events"),
    _rule(r"^(?:(?:equipment |inverter |operational |plant )?(?:alarm|alarme|event|evenement|fault|incident)s?"
          r"(?: code| codes| log| text| message)?|defauts?|pannes?)$",
          ColumnRole.EVENTS, None, _N, "the header names alarms or events"),
    _rule(r"^(?:status|remarks?|comments?|notes?|observations?)$",
          ColumnRole.EVENTS, None, _A, "the header may hold events, or routine status text: look at the values"),
    # --- quantities.  More specific wordings come first.
    _rule(r"(?:baseline|reference|budget|expected) (?:irradiation|irradiance|insolation)", _Q, Metric.BASELINE_IRRADIATION, _N,
          "the header names the irradiation a baseline assumed"),
    _rule(r"curtail|ecret|limitation", _Q, Metric.CURTAILED_ENERGY, _N, "the header names curtailed energy"),
    _rule(r"availab|disponib", _Q, Metric.AVAILABILITY, _N, "the header names availability"),
    _rule(r"soiling loss|soiling losses|perte.* salissure|salissure.* perte|soiling.* loss|dust loss", _Q, Metric.SOILING_RATIO, _N,
          "the header names a soiling loss (0 = clean): it is converted to a soiling ratio", "LOSS"),
    _rule(r"soiling (?:ratio|index|rate)|^sr$|ratio (?:de )?salissure", _Q, Metric.SOILING_RATIO, _N,
          "the header names a soiling ratio (1 = clean)", "RATIO"),
    _rule(r"soiling|salissure|dust", _Q, Metric.SOILING_RATIO, _A,
          "the header speaks of soiling without saying whether it is a ratio (1 = clean) or a loss (0 = clean)", "RATIO"),
    _rule(rf"^{_EXPECTED_WORD}(?: (?:value|ac|kwh))?$|{_EXPECTED_WORD}.* {_ENERGY_WORD}|{_ENERGY_WORD}.* {_EXPECTED_WORD}",
          _Q, Metric.EXPECTED_ENERGY, _N, "the header names an expected or reference production"),
    _rule(r"\bpoa\b|plane of array|in ?plane|tilted|inclin|\bgti\b|plan des modules", _Q, Metric.POA_IRRADIATION, _N,
          "the header names in-plane irradiance"),
    _rule(r"\bghi\b|global horizontal|horizontal", _Q, Metric.GHI, _N, "the header names horizontal irradiance"),
    _rule(r"irradiance|irradiation|insolation|radiation|rayonnement|ensoleillement|eclairement", _Q, Metric.POA_IRRADIATION, _A,
          "the header names irradiance without saying whether it is in the plane of the modules or horizontal"),
    _rule(r"(?:module|panel|panneau|cell|cellule|back ?sheet|\bpv\b).*temp|temp.*(?:module|panel|panneau|cell|cellule)|"
          r"^t ?mod$|^t ?cell$|^tm$", _Q, Metric.MODULE_TEMP, _N, "the header names the module temperature"),
    _rule(r"(?:ambient|ambiante|air|outdoor|outside|exterieur).*temp|temp.*(?:ambient|ambiante|air|exterieur)|"
          r"^t ?amb$|^ta$|^ambient$", _Q, Metric.AMBIENT_TEMP, _N, "the header names the ambient temperature"),
    _rule(r"^(?:temp|temperature|t)$", _Q, Metric.AMBIENT_TEMP, _A,
          "the header names a temperature without saying whether it is the air or the modules"),
    _rule(r"wind|vent\b|^ws$", _Q, Metric.WIND_SPEED, _N, "the header names the wind speed"),
    _rule(r"humid|^rh$|^hr$", _Q, Metric.RELATIVE_HUMIDITY, _N, "the header names the relative humidity"),
    _rule(r"precip|rain|pluie", _Q, Metric.PRECIPITATION, _N, "the header names rainfall"),
    _rule(r"^(?:specific )?yield$", _Q, Metric.ACTUAL_ENERGY, _A,
          "'yield' may be the energy produced or a specific yield (kWh per kWp): check the unit"),
    _rule(rf"{_ENERGY_WORD}|^e ?ac$|^eac$|export|produit|produced|delivered|injected|injecte", _Q, Metric.ACTUAL_ENERGY, _N,
          "the header names the energy produced"),
)

_CANONICAL: dict[str, Metric] = {METRIC_SPECS[m].column: m for m in PLANT_LEVEL_METRICS}


def _unit_fits(metric: Metric, unit: str) -> bool:
    spec = METRIC_SPECS[metric]
    try:
        dimension = dimension_of(unit)
    except UnitError:
        return False
    return dimension == spec.dimension or (dimension == "irradiance" and spec.dimension == "irradiation")


def accepted_units(metric: Metric) -> list[str]:
    """Unit symbols a column of ``metric`` may be declared in: the canonical one first."""
    spec = METRIC_SPECS[metric]
    table = units_by_dimension()

    def of(dimension: str) -> list[str]:
        accepted = table[dimension]["accepted"]
        return [str(u) for u in accepted] if isinstance(accepted, list) else []

    symbols = [spec.unit, *of(spec.dimension)]
    if spec.dimension == "irradiation":
        symbols += of("irradiance")  # mean irradiance: converted with the length of the interval
    seen: set[str] = set()
    out: list[str] = []
    for symbol in symbols:
        if symbol.lower() not in seen:
            seen.add(symbol.lower())
            out.append(symbol)
    return out


def describe_header(header: str) -> ColumnPreview:
    """Role, quantity and unit a header points to - before any value has been looked at."""
    if header == DEFAULT_TIMESTAMP_COLUMN:
        return ColumnPreview(name=header, role=ColumnRole.TIMESTAMP, confidence=Confidence.EXACT, reason="canonical column name")
    if header == DEFAULT_DEVICE_COLUMN:
        return ColumnPreview(name=header, role=ColumnRole.DEVICE, confidence=Confidence.EXACT, reason="canonical column name")
    if header in _CANONICAL:
        metric = _CANONICAL[header]
        return ColumnPreview(
            name=header, role=ColumnRole.QUANTITY, metric=metric, unit=METRIC_SPECS[metric].unit, unit_source="HEADER",
            reported_as="RATIO" if metric is Metric.SOILING_RATIO else None, confidence=Confidence.EXACT,
            reason="canonical column name",
        )
    name, unit = split_header(header)
    for rule in _RULES:
        if not rule.pattern.search(name):
            continue
        if rule.role is not ColumnRole.QUANTITY or rule.metric is None:
            return ColumnPreview(name=header, role=rule.role, confidence=rule.confidence, reason=rule.reason)
        metric = rule.metric
        confidence, reason = rule.confidence, rule.reason
        proposed, source = METRIC_SPECS[metric].unit, "ASSUMED"
        if unit is not None:
            if not _unit_fits(metric, unit):
                wanted = METRIC_SPECS[metric].unit
                return ColumnPreview(
                    name=header, role=ColumnRole.UNUSED,
                    reason=f"the header reads as {metric.value.replace('_', ' ')}, but states {unit}, which is not a unit "
                           f"of that quantity (stored in {wanted}): assign it yourself if it is the right column",
                )
            proposed, source = unit, "HEADER"
        if metric is Metric.SOILING_RATIO and rule.reported_as == "LOSS" and unit is None:
            proposed = "percent"  # a loss is almost always written in percent; flagged as assumed
        return ColumnPreview(
            name=header, role=ColumnRole.QUANTITY, metric=metric, unit=proposed,
            unit_source="HEADER" if source == "HEADER" else "ASSUMED", reported_as=rule.reported_as,
            confidence=confidence, reason=reason,
        )
    return ColumnPreview(name=header, role=ColumnRole.UNUSED, reason="not recognised: assign it yourself, or leave it unused")


# --------------------------------------------------------------------------- values


@dataclass
class _Stats:
    filled: int = 0
    empty: int = 0
    numeric: int = 0
    non_numeric: int = 0
    negative: int = 0
    minimum: float | None = None
    maximum: float | None = None
    samples: list[str] = field(default_factory=list)
    odd_cells: list[str] = field(default_factory=list)
    first: float | None = None
    last: float | None = None
    #: No value is smaller than the one before it.
    never_decreases: bool = True


def _text(raw: Any) -> str:
    return "" if raw is None else " ".join(str(raw).split())


def _column_stats(table: RawTable, column: str) -> _Stats:
    stats = _Stats()
    seen: set[str] = set()
    for row in table.rows:
        raw = row.get(column)
        text = _text(raw)
        if text.lower() in MISSING_TOKENS:
            stats.empty += 1
            continue
        stats.filled += 1
        if text not in seen and len(stats.samples) < SAMPLE_VALUES:
            seen.add(text)
            stats.samples.append(text[:60])
        value, problem = parse_number(raw, table.decimal_comma)
        if value is None or problem is not None:
            stats.non_numeric += 1
            if len(stats.odd_cells) < 3 and text[:40] not in stats.odd_cells:
                stats.odd_cells.append(text[:40])
            continue
        stats.numeric += 1
        if stats.first is None:
            stats.first = value
        elif stats.last is not None and value < stats.last:
            stats.never_decreases = False
        stats.last = value
        if value < 0:
            stats.negative += 1
        stats.minimum = value if stats.minimum is None else min(stats.minimum, value)
        stats.maximum = value if stats.maximum is None else max(stats.maximum, value)
    return stats


def _infer_interval(table: RawTable, column: str, zone_name: str) -> tuple[int | None, int, int, str | None]:
    """(interval in minutes, timestamps read, timestamps not read, an example that was not read)."""
    try:
        zone = get_zone(zone_name)
    except TimelineError:
        zone = get_zone("UTC")
    moments = []
    unread = 0
    example: str | None = None
    for row in table.rows[:TIMESTAMP_SCAN]:
        moment, _problem = parse_timestamp(row.get(column), zone)
        if moment is None:
            unread += 1
            if example is None:
                example = _text(row.get(column))[:40]
        else:
            moments.append(moment)
    ordered = sorted(set(moments))
    steps = Counter(int((b - a).total_seconds() // 60) for a, b in itertools.pairwise(ordered))
    interval = steps.most_common(1)[0][0] if steps else None
    if interval in (DAILY_MINUTES - 60, DAILY_MINUTES + 60):
        interval = DAILY_MINUTES
    return (interval if interval in SUPPORTED_INTERVALS else None), len(moments), unread, example


def _fmt(value: float) -> str:
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:g}"


def preview_table(
    table: RawTable, *, plant: PlantSpec, known_devices: Mapping[str, DeviceSpec] | None = None,
) -> UploadPreview:
    """Describe ``table`` and propose a mapping of its columns.  Nothing is validated or stored here."""
    known_devices = known_devices or {}
    columns = [describe_header(name) for name in table.columns]
    stats = {name: _column_stats(table, name) for name in table.columns}
    notes: list[DataNote] = []

    def note(code: str, severity: Literal["WARNING", "INFO"], message: str, column: str | None = None,
             suggested_unit: str | None = None) -> None:
        notes.append(DataNote(code=code, severity=severity, column=column, message=message, suggested_unit=suggested_unit))

    def unused(column: ColumnPreview, reason: str) -> None:
        column.role, column.metric, column.unit, column.unit_source, column.reported_as = ColumnRole.UNUSED, None, None, None, None
        column.confidence, column.reason = Confidence.NONE, reason

    # ---- a text column cannot be a quantity
    for column in columns:
        s = stats[column.name]
        column.filled, column.empty, column.numeric = s.filled, s.empty, s.numeric
        column.minimum, column.maximum, column.samples = s.minimum, s.maximum, s.samples
        if column.role is ColumnRole.QUANTITY and s.filled > 0 and s.numeric == 0:
            unused(column, "the header fits a quantity, but no cell of the column is a number")
        elif column.role is ColumnRole.CLEANING and s.filled > 0:
            marks = sum(1 for row in table.rows if _text(row.get(column.name)).lower() in CLEANING_TOKENS)
            if marks == 0:
                column.confidence = Confidence.AMBIGUOUS
                column.reason = "the header names cleaning, but no cell is a mark (1, yes, x ...): look at the values"

    # ---- one column per role and per quantity: the surer reading wins, then the first one
    rank = {Confidence.EXACT: 0, Confidence.NAME: 1, Confidence.AMBIGUOUS: 2, Confidence.NONE: 3}
    taken: dict[tuple[ColumnRole, Metric | None], ColumnPreview] = {}
    for column in sorted(columns, key=lambda c: rank[c.confidence]):
        if column.role is ColumnRole.UNUSED:
            continue
        key = (column.role, column.metric)
        holder = taken.get(key)
        if holder is None:
            taken[key] = column
            continue
        if column.role is ColumnRole.TIMESTAMP:
            note("DATE_AND_TIME_IN_TWO_COLUMNS", "WARNING",
                 f"Both '{holder.name}' and '{column.name}' read as a date or a time. SolarWise needs one column holding "
                 "the date and the time together; '" + holder.name + "' was taken.", column.name)
        what = column.metric.value.replace("_", " ") if column.metric is not None else column.role.value.lower()
        unused(column, f"also reads as {what}, which '{holder.name}' already holds: assign it yourself if it is the right one")

    by_role = {c.role: c for c in columns if c.role not in (ColumnRole.QUANTITY, ColumnRole.UNUSED)}
    proposal = MappingProposal(
        timestamp_column=by_role[ColumnRole.TIMESTAMP].name if ColumnRole.TIMESTAMP in by_role else None,
        device_column=by_role[ColumnRole.DEVICE].name if ColumnRole.DEVICE in by_role else None,
        cleaning_column=by_role[ColumnRole.CLEANING].name if ColumnRole.CLEANING in by_role else None,
        event_column=by_role[ColumnRole.EVENTS].name if ColumnRole.EVENTS in by_role else None,
    )
    for column in columns:
        if column.role is ColumnRole.QUANTITY and column.metric is not None and column.unit is not None:
            proposal.channels[column.metric] = ChannelProposal(
                column=column.name, unit=column.unit, reported_as=column.reported_as or "RATIO"
            )

    # ---- timestamps
    interval: int | None = None
    if proposal.timestamp_column is None:
        note("NO_TIMESTAMP_COLUMN", "WARNING",
             "No column could be read as the date or time of each row. Choose it yourself: without it the file cannot be imported.")
    else:
        interval, read, unread, example = _infer_interval(table, proposal.timestamp_column, plant.timezone)
        proposal.interval_minutes = interval
        if unread:
            note("TIMESTAMPS_NOT_READ", "WARNING",
                 f"{unread} of the first {read + unread} values of '{proposal.timestamp_column}' cannot be read as a date"
                 + (f" (for example '{example}')" if example else "")
                 + ". Dates are read as 2026-05-01 or 01/05/2026, with the time as 13:00. Rows that cannot be read are rejected.",
                 proposal.timestamp_column)
        if read and interval is None:
            note("INTERVAL_NOT_REGULAR", "WARNING",
                 "The rows are not 15, 30 or 60 minutes or one day apart. Only these intervals can be imported.",
                 proposal.timestamp_column)
        elif interval is not None:
            label = "one day" if interval == DAILY_MINUTES else f"{interval} minutes"
            note("INTERVAL_READ", "INFO", f"The rows are {label} apart.", proposal.timestamp_column)

    # ---- quantities: units and patterns worth a look
    hours = None if interval is None else (24.0 if interval == DAILY_MINUTES else interval / 60.0)
    capacity = plant.capacity_ac_kw if plant.capacity_ac_kw is not None else plant.capacity_dc_kwp
    for column in columns:
        s = stats[column.name]
        if column.role is not ColumnRole.QUANTITY or column.metric is None or s.maximum is None or s.minimum is None:
            continue
        metric, name = column.metric, column.name
        spec = METRIC_SPECS[metric]
        if column.unit_source == "ASSUMED":
            note("UNIT_NOT_STATED", "INFO",
                 f"The header of '{name}' states no unit: {column.unit} is assumed. Check it.", name)
        if s.non_numeric:
            note("TEXT_IN_NUMERIC_COLUMN", "WARNING",
                 f"{s.non_numeric} cell(s) of '{name}' are not numbers (for example {', '.join(repr(c) for c in s.odd_cells)}). "
                 "They would be rejected and stored as missing, not as zero.", name)
        if s.negative and spec.minimum is not None and spec.minimum >= 0:
            note("NEGATIVE_VALUES", "WARNING",
                 f"{s.negative} value(s) of '{name}' are negative, which is not possible for this quantity. "
                 "They would be rejected and stored as missing.", name)
        if s.numeric >= 10 and s.minimum == s.maximum:
            note("CONSTANT_COLUMN", "INFO", f"'{name}' has the same value ({_fmt(s.maximum)}) on every row.", name)
        if s.filled + s.empty > 0 and s.empty > s.filled:
            note("MOSTLY_EMPTY", "INFO",
                 f"'{name}' is empty on {s.empty} of {s.filled + s.empty} rows. Empty cells stay missing: they are never filled in.", name)

        unit = (column.unit or spec.unit).lower()
        if spec.dimension == "temperature" and unit == "degc" and s.minimum > 200 and s.maximum < 400:
            note("LOOKS_LIKE_KELVIN", "WARNING",
                 f"'{name}' ranges from {_fmt(s.minimum)} to {_fmt(s.maximum)}: that reads as kelvin, not degrees Celsius.", name, "k")
        if metric is Metric.RELATIVE_HUMIDITY and unit == "percent" and s.maximum <= 1.0 and s.numeric >= 5:
            note("LOOKS_LIKE_FRACTION", "WARNING",
                 f"'{name}' never exceeds {_fmt(s.maximum)}: that reads as a fraction (0 to 1), not as a percentage.", name, "fraction")
        if metric is Metric.AVAILABILITY and unit == "fraction" and s.maximum > 1.5:
            note("LOOKS_LIKE_PERCENT", "WARNING",
                 f"'{name}' reaches {_fmt(s.maximum)}: that reads as a percentage, not as a fraction (0 to 1).", name, "percent")
        if metric is Metric.SOILING_RATIO:
            if unit == "fraction" and s.maximum > 1.5:
                note("LOOKS_LIKE_PERCENT", "WARNING",
                     f"'{name}' reaches {_fmt(s.maximum)}: that reads as a percentage, not as a fraction (0 to 1).", name, "percent")
            ceiling = 100.0 if unit == "percent" else 1.0
            if column.reported_as == "RATIO" and s.maximum <= 0.5 * ceiling and s.numeric >= 3:
                note("LOOKS_LIKE_A_LOSS", "WARNING",
                     f"'{name}' never exceeds {_fmt(s.maximum)}. A soiling ratio is close to 1 for a clean array: "
                     "if the column holds a soiling loss (0 = clean), say so in the mapping.", name)
            if column.reported_as == "LOSS" and s.minimum >= 0.5 * ceiling and s.numeric >= 3:
                note("LOOKS_LIKE_A_RATIO", "WARNING",
                     f"'{name}' never goes below {_fmt(s.minimum)}. A soiling loss is close to 0 for a clean array: "
                     "if the column holds a soiling ratio (1 = clean), say so in the mapping.", name)
        if spec.dimension == "irradiation" and unit == "kwh/m2" and hours is not None:
            plausible = 15.0 if interval == DAILY_MINUTES else 1.6 * hours
            if s.maximum > plausible:
                if s.maximum <= MAX_IRRADIANCE_W_M2 and interval != DAILY_MINUTES:
                    note("LOOKS_LIKE_IRRADIANCE", "WARNING",
                         f"'{name}' reaches {_fmt(s.maximum)}: too much for kWh/m2 in one interval. It reads as irradiance in W/m2.",
                         name, "w/m2")
                else:
                    note("IRRADIATION_UNIT_DOUBTFUL", "WARNING",
                         f"'{name}' reaches {_fmt(s.maximum)}: too much for kWh/m2 in one interval. Check the unit "
                         "(Wh/m2, or W/m2 as the mean over the interval).", name, "wh/m2" if s.maximum > MAX_IRRADIANCE_W_M2 else None)
        if metric in (Metric.ACTUAL_ENERGY, Metric.EXPECTED_ENERGY) and hours is not None and unit == "kwh":
            limit = capacity * hours * CAPACITY_MARGIN
            if s.maximum > limit:
                increasing = (
                    s.numeric >= 10 and s.never_decreases and s.first is not None and s.last is not None and s.last > s.first
                )
                if increasing:
                    note("LOOKS_LIKE_A_COUNTER", "WARNING",
                         f"'{name}' only ever increases and reaches {_fmt(s.maximum)}: it reads as a meter counter. "
                         "SolarWise needs the energy of each interval, not the reading of the counter.", name)
                elif s.maximum / 1000.0 <= limit:
                    note("LOOKS_LIKE_WH", "WARNING",
                         f"'{name}' reaches {_fmt(s.maximum)} per interval, more than a plant of {_fmt(capacity)} kW can "
                         f"deliver ({_fmt(limit)} kWh). The values read as Wh.", name, "wh")
                else:
                    note("ENERGY_ABOVE_CAPACITY", "WARNING",
                         f"'{name}' reaches {_fmt(s.maximum)} per interval, more than a plant of {_fmt(capacity)} kW can "
                         f"deliver ({_fmt(limit)} kWh). Check the unit, and the capacity entered for the plant.", name)
            elif 0 < s.maximum < 0.005 * limit and s.maximum * 1000.0 <= limit:
                note("LOOKS_LIKE_MWH", "WARNING",
                     f"'{name}' never exceeds {_fmt(s.maximum)} per interval, very little for a plant of {_fmt(capacity)} kW. "
                     "The values may be in MWh.", name, "mwh")

    # ---- events
    if proposal.event_column is not None:
        s = stats[proposal.event_column]
        texts = Counter(
            _text(row.get(proposal.event_column)) for row in table.rows
            if _text(row.get(proposal.event_column)).lower() not in NO_EVENT_TOKENS
        )
        if not texts:
            note("NO_EVENT_IN_COLUMN", "INFO", f"'{proposal.event_column}' holds no event: every cell is empty or says that nothing happened.",
                 proposal.event_column)
        else:
            note("EVENTS_IN_FILE", "INFO",
                 f"'{proposal.event_column}' holds {sum(texts.values())} marked row(s) with {len(texts)} different text(s), for example "
                 f"{', '.join(repr(t[:40]) for t, _ in texts.most_common(3))}. Each event becomes an evidence record of the dataset.",
                 proposal.event_column)
    if proposal.device_column is not None:
        codes = {_text(row.get(proposal.device_column)) for row in table.rows} - {""}
        unknown = sorted(codes - set(known_devices))
        if unknown:
            note("DEVICES_NOT_REGISTERED", "WARNING",
                 f"{len(unknown)} device code(s) of '{proposal.device_column}' are not registered for this plant "
                 f"(for example {', '.join(unknown[:3])}). Their rows would be ignored: register the devices first.",
                 proposal.device_column)

    # ---- what the file does not contain
    present = set(proposal.channels)
    if Metric.ACTUAL_ENERGY not in present:
        note("NO_ENERGY_COLUMN", "WARNING",
             "No column could be read as the energy produced. Choose it yourself: without it there is nothing to analyse.")
    if Metric.EXPECTED_ENERGY not in present:
        note("NO_EXPECTED_ENERGY", "INFO",
             "The file has no expected or reference production. The analysis then needs another baseline: the typical "
             "year of the plant (tab Typical year and weather), which is a modelled, not a weather-adjusted, reference.")
    if Metric.SOILING_RATIO not in present:
        note("NO_SOILING_MEASUREMENT", "INFO",
             "The file has no soiling measurement. Without a direct soiling measurement the result can be Investigate "
             "or Monitor, never Clean now: a production gap alone does not show soiling.")
    if not present & {Metric.POA_IRRADIATION, Metric.GHI}:
        note("NO_IRRADIANCE", "INFO",
             "The file has no irradiance. The effect of the weather on production then cannot be separated from other causes.")
    if not present & {Metric.MODULE_TEMP, Metric.AMBIENT_TEMP}:
        note("NO_TEMPERATURE", "INFO", "The file has no temperature. Thermal losses then cannot be quantified.")

    sample_rows = [[_text(row.get(name))[:80] for name in table.columns] for row in table.rows[:PREVIEW_ROWS]]
    return UploadPreview(
        file_format=table.file_format,
        rows_total=len(table.rows),
        columns=columns,
        sample_rows=sample_rows,
        proposal=proposal,
        notes=notes,
        embedded_metadata=table.embedded_metadata is not None,
        decimal_comma=table.decimal_comma,
    )
