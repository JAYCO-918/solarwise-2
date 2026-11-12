"""Domain model shared by the scientific engines.

Nothing in :mod:`solarwise.core` touches a database or HTTP; engines exchange
the plain structures defined here.  Bulk time-series rows are slotted
dataclasses (already validated at ingestion), everything else is a Pydantic
model so it can be serialised and returned by the API unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from solarwise.core.provenance import UNKNOWN_TAG, ProvenanceTag

# --------------------------------------------------------------------------- metrics


class Metric(StrEnum):
    ACTUAL_ENERGY = "actual_energy"
    EXPECTED_ENERGY = "expected_energy"
    BASELINE_IRRADIATION = "baseline_irradiation"
    AVAILABILITY = "availability"
    CURTAILED_ENERGY = "curtailed_energy"
    SOILING_RATIO = "soiling_ratio"
    POA_IRRADIATION = "poa_irradiation"
    GHI = "ghi"
    AMBIENT_TEMP = "ambient_temp"
    MODULE_TEMP = "module_temp"
    WIND_SPEED = "wind_speed"
    RELATIVE_HUMIDITY = "relative_humidity"
    PRECIPITATION = "precipitation"
    DEVICE_ENERGY = "device_energy"


@dataclass(frozen=True)
class MetricSpec:
    metric: Metric
    #: Attribute / canonical column name (unit-suffixed).
    column: str
    #: Dimension understood by :mod:`solarwise.core.units`.
    dimension: str
    #: Unit in which the value is stored.
    unit: str
    #: Which table holds it: ``production`` or ``weather``.
    table: str
    description: str
    #: Hard physical bounds, independent of the plant (``None`` = unbounded).
    minimum: float | None = None
    maximum: float | None = None


METRIC_SPECS: dict[Metric, MetricSpec] = {
    Metric.ACTUAL_ENERGY: MetricSpec(
        Metric.ACTUAL_ENERGY, "actual_energy_kwh", "energy", "kWh", "production",
        "AC energy delivered by the plant during the interval", 0.0, None,
    ),
    Metric.EXPECTED_ENERGY: MetricSpec(
        Metric.EXPECTED_ENERGY, "expected_energy_kwh", "energy", "kWh", "production",
        "Baseline (reference) energy for the interval", 0.0, None,
    ),
    Metric.BASELINE_IRRADIATION: MetricSpec(
        Metric.BASELINE_IRRADIATION, "baseline_irradiation_kwh_m2", "irradiation", "kWh/m2", "production",
        "Irradiation assumed by a baseline that is not adjusted to actual irradiance", 0.0, None,
    ),
    Metric.AVAILABILITY: MetricSpec(
        Metric.AVAILABILITY, "availability_fraction", "ratio", "fraction", "production",
        "Capacity-weighted share of the plant technically available", 0.0, 1.0,
    ),
    Metric.CURTAILED_ENERGY: MetricSpec(
        Metric.CURTAILED_ENERGY, "curtailed_energy_kwh", "energy", "kWh", "production",
        "Energy not produced because of grid curtailment, as logged", 0.0, None,
    ),
    Metric.SOILING_RATIO: MetricSpec(
        Metric.SOILING_RATIO, "soiling_ratio", "ratio", "fraction", "production",
        "Output of a soiled reference device relative to a clean one (IEC 61724-1); 1 = clean",
        0.0, 1.05,
    ),
    Metric.POA_IRRADIATION: MetricSpec(
        Metric.POA_IRRADIATION, "poa_irradiation_kwh_m2", "irradiation", "kWh/m2", "weather",
        "In-plane (plane-of-array) irradiation during the interval", 0.0, None,
    ),
    Metric.GHI: MetricSpec(
        Metric.GHI, "ghi_kwh_m2", "irradiation", "kWh/m2", "weather",
        "Global horizontal irradiation during the interval", 0.0, None,
    ),
    Metric.AMBIENT_TEMP: MetricSpec(
        Metric.AMBIENT_TEMP, "ambient_temp_c", "temperature", "degC", "weather",
        "Ambient air temperature (daylight mean preferred for daily data)", -60.0, 65.0,
    ),
    Metric.MODULE_TEMP: MetricSpec(
        Metric.MODULE_TEMP, "module_temp_c", "temperature", "degC", "weather",
        "Module back-surface temperature (irradiance-weighted for daily data)", -60.0, 110.0,
    ),
    Metric.WIND_SPEED: MetricSpec(
        Metric.WIND_SPEED, "wind_speed_ms", "speed", "m/s", "weather", "Wind speed", 0.0, 75.0,
    ),
    Metric.RELATIVE_HUMIDITY: MetricSpec(
        Metric.RELATIVE_HUMIDITY, "relative_humidity_pct", "ratio", "percent", "weather",
        "Relative humidity", 0.0, 100.0,
    ),
    Metric.PRECIPITATION: MetricSpec(
        Metric.PRECIPITATION, "precipitation_mm", "precipitation", "mm", "weather",
        "Precipitation depth during the interval", 0.0, 500.0,
    ),
    Metric.DEVICE_ENERGY: MetricSpec(
        Metric.DEVICE_ENERGY, "actual_energy_kwh", "energy", "kWh", "production",
        "AC energy delivered by one device (inverter) during the interval", 0.0, None,
    ),
}

PLANT_LEVEL_METRICS: tuple[Metric, ...] = tuple(m for m in Metric if m is not Metric.DEVICE_ENERGY)


# --------------------------------------------------------------------------- bulk rows


@dataclass(slots=True)
class Observation:
    """One plant-level interval.  ``None`` always means *not observed*."""

    start_utc: datetime
    actual_energy_kwh: float | None = None
    expected_energy_kwh: float | None = None
    baseline_irradiation_kwh_m2: float | None = None
    availability_fraction: float | None = None
    curtailed_energy_kwh: float | None = None
    soiling_ratio: float | None = None
    poa_irradiation_kwh_m2: float | None = None
    ghi_kwh_m2: float | None = None
    ambient_temp_c: float | None = None
    module_temp_c: float | None = None
    wind_speed_ms: float | None = None
    relative_humidity_pct: float | None = None
    precipitation_mm: float | None = None


@dataclass(slots=True)
class DeviceObservation:
    device_code: str
    start_utc: datetime
    actual_energy_kwh: float | None = None


@dataclass(frozen=True, slots=True)
class DeviceSpec:
    code: str
    capacity_kwp: float
    kind: str = "INVERTER"


# --------------------------------------------------------------------------- metadata


class MeteringBoundary(StrEnum):
    GRID_METER = "GRID_METER"
    INVERTER_AC = "INVERTER_AC"
    DC_COMBINER = "DC_COMBINER"
    UNKNOWN = "UNKNOWN"


class IrradiancePlane(StrEnum):
    POA = "POA"
    GHI = "GHI"


class SoilingMethod(StrEnum):
    """How a soiling figure was obtained."""

    SOILING_STATION = "SOILING_STATION"
    CLEAN_REFERENCE_MODULE = "CLEAN_REFERENCE_MODULE"
    STRING_COMPARISON = "STRING_COMPARISON"
    IV_CURVE = "IV_CURVE"
    OPTICAL_SENSOR = "OPTICAL_SENSOR"
    VALIDATED_MODEL = "VALIDATED_MODEL"
    VISUAL_ESTIMATE = "VISUAL_ESTIMATE"
    UNSPECIFIED = "UNSPECIFIED"


#: Methods that yield a *quantified* soiling ratio by direct comparison.
DIRECT_SOILING_METHODS: frozenset[SoilingMethod] = frozenset(
    {
        SoilingMethod.SOILING_STATION,
        SoilingMethod.CLEAN_REFERENCE_MODULE,
        SoilingMethod.STRING_COMPARISON,
        SoilingMethod.IV_CURVE,
        SoilingMethod.OPTICAL_SENSOR,
    }
)


class ChannelMeta(BaseModel):
    """Declared properties of one data channel of a dataset."""

    model_config = ConfigDict(frozen=True)

    metric: Metric
    tag: ProvenanceTag = UNKNOWN_TAG
    unit: str
    original_unit: str | None = None
    #: Declared relative standard uncertainty (one sigma) in percent of value.
    uncertainty_pct: float | None = Field(default=None, ge=0, le=100)
    #: Declared absolute standard uncertainty (one sigma) in the stored unit.
    uncertainty_abs: float | None = Field(default=None, ge=0)
    #: Where energy is metered (energy channels only).
    boundary: MeteringBoundary | None = None
    #: Plane of a baseline reference irradiation channel.
    plane: IrradiancePlane | None = None
    #: How a soiling-ratio channel is obtained.
    soiling_method: SoilingMethod | None = None
    notes: str | None = Field(default=None, max_length=1000)


class BaselineMethod(StrEnum):
    OPERATOR_SUPPLIED = "OPERATOR_SUPPLIED"
    PVGIS_TYPICAL_YEAR = "PVGIS_TYPICAL_YEAR"
    TELEMETRY_MODEL = "TELEMETRY_MODEL"
    HISTORICAL_CLEAN_REFERENCE = "HISTORICAL_CLEAN_REFERENCE"
    ENGINEERING_MODEL = "ENGINEERING_MODEL"
    UNKNOWN = "UNKNOWN"


class BaselineDescriptor(BaseModel):
    """What the expected-energy baseline does and does not account for.

    ``None`` on a boolean means *not declared*; the engines then treat the
    effect as not accounted for **and** not quantifiable, and say so.
    """

    model_config = ConfigDict(frozen=True)

    method: BaselineMethod = BaselineMethod.UNKNOWN
    #: Does the baseline reflect the irradiance actually received?
    irradiance_adjusted: bool | None = None
    #: Does the baseline reflect the temperatures actually experienced?
    temperature_adjusted: bool | None = None
    #: Cell temperature implicit in a baseline that is not temperature adjusted.
    reference_cell_temp_c: float | None = Field(default=None, ge=-20, le=100)
    #: Does the baseline include age-related degradation?
    degradation_adjusted: bool | None = None
    #: Soiling loss already assumed inside the baseline (0.02 = 2 %).
    soiling_allowance_fraction: float | None = Field(default=None, ge=0, lt=0.5)
    description: str | None = Field(default=None, max_length=1000)


_NoteKey = Annotated[str, StringConstraints(max_length=80)]
_NoteText = Annotated[str, StringConstraints(max_length=1000)]


class TrackingType(StrEnum):
    FIXED = "FIXED"
    SINGLE_AXIS = "SINGLE_AXIS"
    DUAL_AXIS = "DUAL_AXIS"


class PlantSpec(BaseModel):
    """Engineering description of a plant, as needed by the engines."""

    name: str = Field(min_length=1, max_length=200)
    capacity_dc_kwp: float = Field(gt=0)
    capacity_ac_kw: float | None = Field(default=None, gt=0)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = Field(default="UTC", max_length=64)
    tracking: TrackingType = TrackingType.FIXED
    tilt_deg: float | None = Field(default=None, ge=0, le=90)
    azimuth_deg: float | None = Field(default=None, ge=0, lt=360)
    #: Module power temperature coefficient [1/degC], negative.
    module_temp_coeff_per_c: float | None = Field(default=None, lt=0, gt=-0.01)
    noct_c: float | None = Field(default=None, ge=30, le=60)
    #: Losses of a clean, available array other than temperature.
    system_loss_fraction: float | None = Field(default=None, ge=0, lt=0.6)
    module_area_m2: float | None = Field(default=None, gt=0)
    commissioning_date: date | None = None
    annual_degradation_rate: float | None = Field(default=None, ge=0, lt=0.05)
    #: ``True`` for reference / demonstration plants.  Such a plant can never
    #: receive an operational authorisation.
    is_demonstration: bool = False
    #: parameter name -> note on where the value comes from.
    parameter_notes: dict[_NoteKey, _NoteText] = Field(default_factory=dict, max_length=60)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("the plant name is empty")
        return value


# --------------------------------------------------------------------------- evidence records


class EvidenceType(StrEnum):
    SOILING_MEASUREMENT = "SOILING_MEASUREMENT"
    VISUAL_INSPECTION = "VISUAL_INSPECTION"
    INVERTER_FAULT = "INVERTER_FAULT"
    SHADING_OBSERVATION = "SHADING_OBSERVATION"
    CURTAILMENT_EVENT = "CURTAILMENT_EVENT"
    GRID_OUTAGE = "GRID_OUTAGE"
    SENSOR_FAULT = "SENSOR_FAULT"
    CLEANING_EVENT = "CLEANING_EVENT"
    OTHER = "OTHER"


class InspectionFinding(StrEnum):
    SOILING_HEAVY = "SOILING_HEAVY"
    SOILING_LIGHT = "SOILING_LIGHT"
    CLEAN = "CLEAN"
    SHADING = "SHADING"
    EQUIPMENT_DAMAGE = "EQUIPMENT_DAMAGE"
    NO_FINDING = "NO_FINDING"


class EvidenceRecord(BaseModel):
    """A discrete, documented observation (manual entry, log extract, inspection)."""

    model_config = ConfigDict(frozen=True)

    reference: str = Field(max_length=64)
    evidence_type: EvidenceType
    observed_start: datetime
    observed_end: datetime | None = None
    tag: ProvenanceTag = UNKNOWN_TAG
    description: str = Field(default="", max_length=2000)
    #: Numeric finding.  For ``SOILING_MEASUREMENT`` this is the soiling ratio.
    value: float | None = None
    unit: str | None = None
    std_uncertainty: float | None = Field(default=None, ge=0)
    soiling_method: SoilingMethod | None = None
    finding: InspectionFinding | None = None
    device_code: str | None = None
    #: For faults/outages: has the issue been closed?
    resolved: bool | None = None
    document_ref: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check(self) -> EvidenceRecord:
        if self.observed_start.tzinfo is None:
            raise ValueError("observed_start must be timezone-aware")
        if self.observed_end is not None:
            if self.observed_end.tzinfo is None:
                raise ValueError("observed_end must be timezone-aware")
            if self.observed_end < self.observed_start:
                raise ValueError("observed_end precedes observed_start")
        if self.evidence_type is EvidenceType.SOILING_MEASUREMENT and self.value is not None and not (
            0.0 < self.value <= 1.05
        ):
            raise ValueError("a soiling ratio must lie within (0, 1.05]")
        return self


# --------------------------------------------------------------------------- thresholds


class AnalysisThresholds(BaseModel):
    """Engineering thresholds used by the rule engines.

    These are *technical assumptions*, not physical constants.  Every one of
    them is recorded with each analysis and can be overridden per request.
    See ``docs/SCIENTIFIC_METHODOLOGY.md`` for the rationale of each default.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: A relative gap below this is treated as normal variation [%].
    gap_materiality_pct: float = Field(default=3.0, gt=0, le=50)
    #: A relative gap above this is called severe [%].
    gap_severe_pct: float = Field(default=10.0, gt=0, le=100)
    #: Coverage factor k applied to standard uncertainties (2 ~ 95 %).
    coverage_factor: float = Field(default=2.0, ge=1, le=4)
    #: Minimum share of daylight intervals with both expected and actual data.
    min_data_completeness: float = Field(default=0.90, gt=0, le=1)
    #: Length of the most recent window describing the *current* plant state [days].
    assessment_window_days: int = Field(default=7, ge=3, le=31)
    #: A measured soiling loss below this is not treated as credible evidence [%].
    soiling_credibility_floor_pct: float = Field(default=2.0, ge=0, le=20)
    #: Maximum age of a spot soiling measurement relative to the period end [days].
    soiling_measurement_max_age_days: int = Field(default=7, ge=0, le=60)
    #: Allowed disagreement between measured soiling loss and the gap it should explain [% points].
    consistency_tolerance_pct: float = Field(default=3.0, gt=0, le=20)
    #: Daily rainfall assumed to clean the array (Kimber et al. 2006 use ~6 mm) [mm].
    rain_cleaning_threshold_mm: float = Field(default=6.0, gt=0, le=50)
    #: Minimum dry spell before a downward trend is read as possible soiling [days].
    min_dry_days_for_trend: int = Field(default=14, ge=3, le=120)
    #: Availability below this in the assessment window counts as an open equipment issue.
    availability_alert_fraction: float = Field(default=0.99, gt=0, le=1)
    #: A device yielding less than this share of the fleet median is under-performing.
    device_underperformance_ratio: float = Field(default=0.90, gt=0, lt=1)
    #: Actual below this share of expected (in daylight) marks a full outage interval.
    outage_actual_fraction: float = Field(default=0.02, ge=0, lt=0.5)
    #: Excess loss near sunrise/sunset over midday that suggests shading [% points].
    shading_edge_excess_pct: float = Field(default=10.0, gt=0, le=100)
    #: A level shift of the performance index larger than this is an abrupt change [% points].
    step_change_min_drop_pct: float = Field(default=3.0, gt=0, le=50)
    #: A quantified effect smaller than this share of expected energy is immaterial [%].
    factor_materiality_pct: float = Field(default=1.0, gt=0, le=20)
