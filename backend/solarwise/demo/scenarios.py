"""The ten demonstration scenarios.

Each scenario is a synthetic dataset with one known, deliberately injected
situation, plus the evidence records and (illustrative) economic assumptions
that go with it.  The expected outcome of each scenario is stated here and
asserted by the test-suite: the scenarios are the regression fixtures of the
decision logic.

All monetary values are *illustrative user assumptions*.  They are not market
prices, not tariffs and not contractual prices.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from solarwise.core.economics import EconomicInputs, EnergyValueBasis, ValueClassification
from solarwise.core.models import (
    BaselineDescriptor,
    BaselineMethod,
    DeviceSpec,
    EvidenceRecord,
    EvidenceType,
    InspectionFinding,
    MeteringBoundary,
    Metric,
    PlantSpec,
    SoilingMethod,
)
from solarwise.core.provenance import Provenance, ProvenanceTag
from solarwise.core.recoverable import CleaningAssumptions
from solarwise.demo.generator import (
    DEFAULT_SEED,
    GENERATOR_NAME,
    GENERATOR_VERSION,
    REFERENCE_DEVICES,
    REFERENCE_PLANT,
    SYNTHETIC_STATEMENT,
    Effects,
    generate_daily_rows,
    generate_hourly_rows,
    generate_weather,
    stream,
)
from solarwise.ingestion.schema import ChannelDeclaration, DatasetMetadata, SyntheticDeclaration

#: First day of the 60-day daily scenarios and of the 21-day hourly scenarios.
DAILY_START = date(2026, 5, 1)
DAILY_DAYS = 60
HOURLY_START = date(2026, 6, 9)
HOURLY_DAYS = 21

_ASSUMPTION_NOTE = "Illustrative demonstration assumption - not a market price, tariff or contractual value."


@dataclass
class Scenario:
    key: str
    number: int
    title: str
    #: What the scenario is meant to show, in one or two sentences.
    story: str
    #: Ground truth: what the generator injected.
    injected: list[str]
    interval_minutes: int
    #: Plant-level rows followed by device-level rows, in upload format.
    rows: list[dict[str, Any]]
    metadata: DatasetMetadata
    evidence: list[EvidenceRecord]
    cleaning: CleaningAssumptions | None
    economics: EconomicInputs | None
    expected_decision: str
    expected_rule: str
    expected_diagnostic_status: str
    plant: PlantSpec = field(default_factory=lambda: REFERENCE_PLANT)
    devices: tuple[DeviceSpec, ...] = ()
    period_start: date = DAILY_START
    period_end: date = DAILY_START
    extra: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- shared declarations


def demo_cleaning(horizon: float = 30.0, low: float = 21.0, high: float = 45.0, note: str | None = None) -> CleaningAssumptions:
    return CleaningAssumptions(
        cleaning_effectiveness=0.90,
        cleaning_effectiveness_low=0.80,
        cleaning_effectiveness_high=0.98,
        benefit_horizon_days=horizon,
        benefit_horizon_days_low=low,
        benefit_horizon_days_high=high,
        source_note=note or "Illustrative demonstration assumption (no rain expected during the dry season).",
    )


def demo_economics() -> EconomicInputs:
    return EconomicInputs(
        currency="DZD",
        energy_value_per_kwh=5.0,
        energy_value_basis=EnergyValueBasis.INTERNAL_VALUATION,
        energy_value_classification=ValueClassification.USER_ASSUMPTION,
        energy_value_source=_ASSUMPTION_NOTE,
        water_volume_m3=1500.0,
        water_price_per_m3=80.0,
        labour_hours=6000.0,
        labour_rate_per_hour=400.0,
        equipment_cost=1_500_000.0,
        operational_cost=500_000.0,
        downtime_cost=0.0,
        cost_uncertainty_pct=20.0,
        cost_classification=ValueClassification.USER_ASSUMPTION,
        cost_source=_ASSUMPTION_NOTE,
    )


def _declare(source: str, emulates: Provenance | None, **extra: Any) -> ChannelDeclaration:
    return ChannelDeclaration(provenance=Provenance.SYNTHETIC, emulates=emulates, source=source, **extra)


def _channels(
    present: set[str], *, emulate: bool = True, soiling_method: SoilingMethod = SoilingMethod.SOILING_STATION
) -> dict[Metric, ChannelDeclaration]:
    """Channel declarations for the columns present in a scenario."""
    measured = Provenance.MEASURED if emulate else None
    modelled = Provenance.MODELLED if emulate else None
    prefix = "Synthetic stand-in for " if emulate else "Synthetic series: "
    table: dict[str, tuple[Metric, ChannelDeclaration]] = {
        "actual_energy_kwh": (
            Metric.ACTUAL_ENERGY,
            _declare(prefix + "revenue-meter energy", measured, uncertainty_pct=0.5, boundary=MeteringBoundary.GRID_METER),
        ),
        "expected_energy_kwh": (
            Metric.EXPECTED_ENERGY,
            _declare(prefix + "a weather-adjusted performance model", modelled, uncertainty_pct=2.0,
                     boundary=MeteringBoundary.GRID_METER),
        ),
        "availability_fraction": (Metric.AVAILABILITY, _declare(prefix + "a SCADA availability log", measured)),
        "curtailed_energy_kwh": (
            Metric.CURTAILED_ENERGY, _declare(prefix + "the plant controller's curtailment log", measured),
        ),
        "soiling_ratio": (
            Metric.SOILING_RATIO,
            _declare(prefix + "a soiling station (clean / soiled reference cells)", measured,
                     uncertainty_abs=0.005, soiling_method=soiling_method),
        ),
        "poa_irradiation_kwh_m2": (Metric.POA_IRRADIATION, _declare(prefix + "an in-plane pyranometer", measured)),
        "ghi_kwh_m2": (Metric.GHI, _declare(prefix + "a horizontal pyranometer", measured)),
        "ambient_temp_c": (Metric.AMBIENT_TEMP, _declare(prefix + "a weather-station thermometer", measured)),
        "module_temp_c": (Metric.MODULE_TEMP, _declare(prefix + "back-of-module temperature sensors", measured)),
        "wind_speed_ms": (Metric.WIND_SPEED, _declare(prefix + "a weather-station anemometer", measured)),
        "precipitation_mm": (Metric.PRECIPITATION, _declare(prefix + "a weather-station rain gauge", measured)),
    }
    return {metric: declaration for column, (metric, declaration) in table.items() if column in present}


def _baseline(temperature_adjusted: bool = True) -> BaselineDescriptor:
    return BaselineDescriptor(
        method=BaselineMethod.TELEMETRY_MODEL,
        irradiance_adjusted=True,
        temperature_adjusted=temperature_adjusted,
        reference_cell_temp_c=None if temperature_adjusted else 25.0,
        degradation_adjusted=True,
        soiling_allowance_fraction=0.0,
        description=(
            "Synthetic stand-in for an expected-energy model driven by measured in-plane irradiation"
            + (" and module temperature." if temperature_adjusted else "; rated at 25 degC, temperature is NOT considered.")
        ),
    )


def _metadata(
    key: str, title: str, rows: list[dict[str, Any]], interval: int, seed: int, injected: list[str], *,
    emulate: bool = True, temperature_adjusted: bool = True, parameters: dict[str, Any] | None = None,
) -> DatasetMetadata:
    present = {column for row in rows for column in row}
    return DatasetMetadata(
        name=f"Demo scenario - {title}",
        description=f"Synthetic scenario '{key}'. " + SYNTHETIC_STATEMENT,
        timezone=REFERENCE_PLANT.timezone,
        interval_minutes=interval,
        channels=_channels(present, emulate=emulate),
        baseline=_baseline(temperature_adjusted),
        capacity_dc_kwp=REFERENCE_PLANT.capacity_dc_kwp,
        synthetic=SyntheticDeclaration(
            generator=GENERATOR_NAME,
            generator_version=GENERATOR_VERSION,
            seed=seed,
            statement=SYNTHETIC_STATEMENT,
            parameters={"scenario": key, **(parameters or {})},
            injected_effects=injected,
        ),
        disclaimer=SYNTHETIC_STATEMENT,
    )


def _tag(source: str, emulate: bool = True) -> ProvenanceTag:
    return ProvenanceTag(
        provenance=Provenance.SYNTHETIC,
        emulates=Provenance.MEASURED if emulate else None,
        source=source,
    )


def _at(day: date, hour: int = 10) -> datetime:
    return datetime.combine(day, time(hour=hour), tzinfo=ZoneInfo(REFERENCE_PLANT.timezone))


def _day(index: int, start: date = DAILY_START) -> date:
    return start + timedelta(days=index)


# --------------------------------------------------------------------------- scenario builders


def _s01(seed: int) -> Scenario:
    key, title = "S01_normal_operation", "Normal operation"
    rng = stream(seed, key)
    weather = generate_weather(DAILY_START, DAILY_DAYS, REFERENCE_PLANT, rng)
    effects = Effects(
        soiling_ratio=dict.fromkeys(range(DAILY_DAYS), 0.995), availability=dict.fromkeys(range(DAILY_DAYS), 0.998)
    )
    rows, _ = generate_daily_rows(weather, REFERENCE_PLANT, effects, rng)
    injected = ["No fault injected: array near clean (soiling ratio 0.995), availability 99.8 %."]
    return Scenario(
        key=key, number=1, title=title,
        story="Production follows the baseline. Nothing calls for action; the system should say so.",
        injected=injected, interval_minutes=1440, rows=rows,
        metadata=_metadata(key, title, rows, 1440, seed, injected),
        evidence=[], cleaning=demo_cleaning(), economics=demo_economics(),
        expected_decision="MONITOR", expected_rule="R6", expected_diagnostic_status="NO_SIGNIFICANT_DEVIATION",
        period_start=DAILY_START, period_end=_day(DAILY_DAYS - 1),
    )


def _soiling_ramp(rate_per_day: float) -> dict[int, float]:
    return {i: 1.0 - rate_per_day * (i + 1) for i in range(DAILY_DAYS)}


def _s02(seed: int, *, key: str = "S02_confirmed_soiling", number: int = 2, emulate: bool = True) -> Scenario:
    title = "Confirmed soiling" if emulate else "Synthetic demonstration (no evidence role declared)"
    rng = stream(seed, "S02_confirmed_soiling")  # S09 deliberately reuses the same numbers
    weather = generate_weather(DAILY_START, DAILY_DAYS, REFERENCE_PLANT, rng)
    ramp = _soiling_ramp(0.0015)
    effects = Effects(soiling_ratio=ramp, availability=dict.fromkeys(range(DAILY_DAYS), 0.998))
    rows, _ = generate_daily_rows(weather, REFERENCE_PLANT, effects, rng)
    injected = [
        "Soiling accumulating at 0.15 % per day since a cleaning on the day before the period "
        "(soiling ratio 0.91 on the last day).",
        "Availability 99.8 %; no equipment fault, no curtailment.",
    ]
    evidence = [
        EvidenceRecord(
            reference="DEMO-CLEAN-0430", evidence_type=EvidenceType.CLEANING_EVENT,
            observed_start=_at(DAILY_START - timedelta(days=1), 6), tag=_tag("Synthetic stand-in for a maintenance log", emulate),
            description="Full-site cleaning (synthetic record).",
        ),
        EvidenceRecord(
            reference="DEMO-INSP-0626", evidence_type=EvidenceType.VISUAL_INSPECTION,
            observed_start=_at(_day(56)), tag=_tag("Synthetic stand-in for an inspection report", emulate),
            description="Uniform dust layer on all inspected rows (synthetic record).",
            finding=InspectionFinding.SOILING_HEAVY,
        ),
        EvidenceRecord(
            reference="DEMO-SRTEST-0627", evidence_type=EvidenceType.SOILING_MEASUREMENT,
            observed_start=_at(_day(57), 12), tag=_tag("Synthetic stand-in for a clean-reference string test", emulate),
            description="Freshly cleaned strings compared with adjacent uncleaned strings at midday (synthetic record).",
            value=round(ramp[57], 3), unit="fraction", std_uncertainty=0.006,
            soiling_method=SoilingMethod.STRING_COMPARISON,
        ),
    ]
    if emulate:
        story = (
            "A steady decline since the last cleaning, a soiling station and a clean-reference string test that "
            "agree with the production gap, no technical issue, and economics that pay: the case in which a "
            "cleaning is justified. Being synthetic, the decision is simulated."
        )
        expected = ("CLEAN_NOW", "R3", "SINGLE_EXPLANATION")
    else:
        story = (
            "Numerically identical to scenario 2, but the data are declared plainly synthetic, with no evidence "
            "role. The system must refuse to draw any cleaning conclusion from them."
        )
        expected = ("INVESTIGATE", "R0", "INSUFFICIENT_DATA")
    return Scenario(
        key=key, number=number, title=title, story=story, injected=injected, interval_minutes=1440, rows=rows,
        metadata=_metadata(key, title, rows, 1440, seed, injected, emulate=emulate, parameters={"soiling_rate_per_day": 0.0015}),
        evidence=evidence, cleaning=demo_cleaning(), economics=demo_economics(),
        expected_decision=expected[0], expected_rule=expected[1], expected_diagnostic_status=expected[2],
        period_start=DAILY_START, period_end=_day(DAILY_DAYS - 1),
    )


def _s03(seed: int) -> Scenario:
    key, title = "S03_temperature_effect", "Temperature effect"
    rng = stream(seed, key)
    weather = generate_weather(DAILY_START, DAILY_DAYS, REFERENCE_PLANT, rng)
    effects = Effects(
        soiling_ratio=dict.fromkeys(range(DAILY_DAYS), 0.995), availability=dict.fromkeys(range(DAILY_DAYS), 0.998),
        baseline_ignores_temperature=True,
    )
    rows, _ = generate_daily_rows(weather, REFERENCE_PLANT, effects, rng)
    injected = [
        "The baseline delivered with the data is rated at 25 degC and ignores operating temperature.",
        "Array near clean (soiling ratio 0.995), availability 99.8 %.",
    ]
    return Scenario(
        key=key, number=3, title=title,
        story="A large gap against a baseline that ignores heat. The loss is thermal and expected; cleaning would not recover it.",
        injected=injected, interval_minutes=1440, rows=rows,
        metadata=_metadata(key, title, rows, 1440, seed, injected, temperature_adjusted=False),
        evidence=[], cleaning=demo_cleaning(), economics=demo_economics(),
        expected_decision="MONITOR", expected_rule="R6", expected_diagnostic_status="SINGLE_EXPLANATION",
        period_start=DAILY_START, period_end=_day(DAILY_DAYS - 1),
    )


def _s04(seed: int) -> Scenario:
    key, title = "S04_inverter_fault", "Inverter fault"
    rng = stream(seed, key)
    weather = generate_weather(DAILY_START, DAILY_DAYS, REFERENCE_PLANT, rng)
    down = frozenset({"BLK-07", "BLK-13"})
    effects = Effects(
        soiling_ratio=dict.fromkeys(range(DAILY_DAYS), 0.995),
        devices_down=dict.fromkeys(range(44, DAILY_DAYS), down),
    )
    rows, device_rows = generate_daily_rows(weather, REFERENCE_PLANT, effects, rng, devices=REFERENCE_DEVICES)
    injected = [
        "Blocks BLK-07 and BLK-13 (2 of 20, 10 % of capacity) out of service from day 45 to the end of the period.",
        "Array near clean (soiling ratio 0.995).",
    ]
    evidence = [
        EvidenceRecord(
            reference=f"DEMO-FAULT-{code[-2:]}", evidence_type=EvidenceType.INVERTER_FAULT,
            observed_start=_at(_day(44), 7), tag=_tag("Synthetic stand-in for an inverter alarm log"),
            description="Inverter tripped and did not restart (synthetic record).", device_code=code, resolved=False,
        )
        for code in sorted(down)
    ]
    return Scenario(
        key=key, number=4, title=title,
        story="Two inverter blocks stop producing. The gap is real but it is an equipment problem: the system must ask for a repair, not a cleaning.",
        injected=injected, interval_minutes=1440, rows=rows + device_rows,
        metadata=_metadata(key, title, rows, 1440, seed, injected),
        evidence=evidence, cleaning=demo_cleaning(), economics=demo_economics(),
        expected_decision="INVESTIGATE", expected_rule="R1", expected_diagnostic_status="SINGLE_EXPLANATION",
        devices=REFERENCE_DEVICES, period_start=DAILY_START, period_end=_day(DAILY_DAYS - 1),
    )


def _s05(seed: int) -> Scenario:
    key, title = "S05_shading", "Morning shading"
    rng = stream(seed, key)
    weather = generate_weather(HOURLY_START, HOURLY_DAYS, REFERENCE_PLANT, rng)
    effects = Effects(soiling_ratio=dict.fromkeys(range(HOURLY_DAYS), 0.995), morning_shading_loss=0.45)
    rows = generate_hourly_rows(weather, REFERENCE_PLANT, effects, rng)
    injected = [
        "45 % of production lost during the first third of every day (an obstruction to the east).",
        "Array near clean (soiling ratio 0.995).",
    ]
    return Scenario(
        key=key, number=5, title=title,
        story="Losses confined to the morning, every day, while midday is unaffected. A pattern typical of shading that calls for a site inspection.",
        injected=injected, interval_minutes=60, rows=rows,
        metadata=_metadata(key, title, rows, 60, seed, injected),
        evidence=[], cleaning=demo_cleaning(), economics=demo_economics(),
        expected_decision="INVESTIGATE", expected_rule="R4", expected_diagnostic_status="MULTIPLE_PLAUSIBLE",
        period_start=HOURLY_START, period_end=_day(HOURLY_DAYS - 1, HOURLY_START),
    )


def _s06(seed: int) -> Scenario:
    key, title = "S06_curtailment", "Grid curtailment"
    rng = stream(seed, key)
    weather = generate_weather(HOURLY_START, HOURLY_DAYS, REFERENCE_PLANT, rng)
    days = (3, 4, 9, 10, 15, 16, 17, 19)
    effects = Effects(soiling_ratio=dict.fromkeys(range(HOURLY_DAYS), 0.995), curtailment_cap=dict.fromkeys(days, 0.55))
    rows = generate_hourly_rows(weather, REFERENCE_PLANT, effects, rng, include_curtailment_log=True)
    injected = [
        f"Active power limited to 55 % of the AC rating between 10:00 and 16:00 on {len(days)} days; "
        "the withheld energy is logged by the plant controller.",
        "Array near clean (soiling ratio 0.995).",
    ]
    evidence = [
        EvidenceRecord(
            reference=f"DEMO-CURT-{_day(i, HOURLY_START):%m%d}", evidence_type=EvidenceType.CURTAILMENT_EVENT,
            observed_start=_at(_day(i, HOURLY_START), 10), observed_end=_at(_day(i, HOURLY_START), 16),
            tag=_tag("Synthetic stand-in for a grid-operator dispatch instruction"),
            description="Active-power set-point 55 % of rated power (synthetic record).", resolved=True,
        )
        for i in days
    ]
    return Scenario(
        key=key, number=6, title=title,
        story="Output is capped on instruction of the grid operator and the withheld energy is logged. The gap is fully explained; there is nothing to clean.",
        injected=injected, interval_minutes=60, rows=rows,
        metadata=_metadata(key, title, rows, 60, seed, injected),
        evidence=evidence, cleaning=demo_cleaning(), economics=demo_economics(),
        expected_decision="MONITOR", expected_rule="R6", expected_diagnostic_status="SINGLE_EXPLANATION",
        period_start=HOURLY_START, period_end=_day(HOURLY_DAYS - 1, HOURLY_START),
    )


def _s07(seed: int) -> Scenario:
    key, title = "S07_missing_data", "Missing data"
    rng = stream(seed, key)
    weather = generate_weather(DAILY_START, DAILY_DAYS, REFERENCE_PLANT, rng)
    missing = frozenset({8, 9, 17, 31, 32, 40, 53, 54, 56, 58})
    absent = frozenset({20, 21, 22})
    effects = Effects(
        soiling_ratio=_soiling_ramp(0.0010), availability=dict.fromkeys(range(DAILY_DAYS), 0.998),
        missing_actual_days=missing, absent_days=absent,
    )
    rows, _ = generate_daily_rows(weather, REFERENCE_PLANT, effects, rng, include_soiling_channel=False)
    injected = [
        f"Production telemetry missing on {len(missing)} days (4 of the last 7) and no row at all for {len(absent)} days.",
        "A soiling loss is present in the underlying series but no soiling measurement is supplied.",
    ]
    return Scenario(
        key=key, number=7, title=title,
        story="Too much of the recent production record is missing. The system must not fill the holes or guess; it must ask for the data.",
        injected=injected, interval_minutes=1440, rows=rows,
        metadata=_metadata(key, title, rows, 1440, seed, injected),
        evidence=[], cleaning=demo_cleaning(), economics=demo_economics(),
        expected_decision="INVESTIGATE", expected_rule="R0", expected_diagnostic_status="INSUFFICIENT_DATA",
        period_start=DAILY_START, period_end=_day(DAILY_DAYS - 1),
    )


def _s08(seed: int) -> Scenario:
    key, title = "S08_conflicting_evidence", "Conflicting evidence"
    rng = stream(seed, key)
    weather = generate_weather(DAILY_START, DAILY_DAYS, REFERENCE_PLANT, rng)
    effects = Effects(
        soiling_ratio=_soiling_ramp(0.0015),
        reported_soiling_ratio=dict.fromkeys(range(DAILY_DAYS), 0.99),
        availability=dict.fromkeys(range(DAILY_DAYS), 0.998),
    )
    rows, _ = generate_daily_rows(weather, REFERENCE_PLANT, effects, rng)
    injected = [
        "The array soils at 0.15 % per day, but the soiling station keeps reporting 0.99 "
        "(its 'clean' reference cell is itself dirty).",
        "An inspection reports heavy soiling.",
    ]
    evidence = [
        EvidenceRecord(
            reference="DEMO-INSP-0627", evidence_type=EvidenceType.VISUAL_INSPECTION,
            observed_start=_at(_day(57)), tag=_tag("Synthetic stand-in for an inspection report"),
            description="Thick dust layer on all inspected rows (synthetic record).",
            finding=InspectionFinding.SOILING_HEAVY,
        )
    ]
    return Scenario(
        key=key, number=8, title=title,
        story="The soiling station says 'clean', an inspection says 'heavily soiled', and production is 9 % short. The sources contradict each other; the system must not pick one.",
        injected=injected, interval_minutes=1440, rows=rows,
        metadata=_metadata(key, title, rows, 1440, seed, injected),
        evidence=evidence, cleaning=demo_cleaning(), economics=demo_economics(),
        expected_decision="INVESTIGATE", expected_rule="R2", expected_diagnostic_status="CONFLICTING_EVIDENCE",
        period_start=DAILY_START, period_end=_day(DAILY_DAYS - 1),
    )


def _s09(seed: int) -> Scenario:
    return _s02(seed, key="S09_synthetic_demonstration", number=9, emulate=False)


def _s10(seed: int) -> Scenario:
    key, title = "S10_unprofitable_cleaning", "Unprofitable cleaning"
    rng = stream(seed, key)
    weather = generate_weather(DAILY_START, DAILY_DAYS, REFERENCE_PLANT, rng)
    ramp = _soiling_ramp(0.00095)
    effects = Effects(soiling_ratio=ramp, availability=dict.fromkeys(range(DAILY_DAYS), 0.998))
    rows, _ = generate_daily_rows(weather, REFERENCE_PLANT, effects, rng)
    injected = [
        "Soiling accumulating at 0.095 % per day (soiling ratio 0.943 on the last day).",
        "Benefit horizon assumed to be only 3 days (natural cleaning expected).",
    ]
    evidence = [
        EvidenceRecord(
            reference="DEMO-SRTEST-0627", evidence_type=EvidenceType.SOILING_MEASUREMENT,
            observed_start=_at(_day(57), 12), tag=_tag("Synthetic stand-in for a clean-reference string test"),
            description="Freshly cleaned strings compared with adjacent uncleaned strings at midday (synthetic record).",
            value=round(ramp[57], 3), unit="fraction", std_uncertainty=0.006,
            soiling_method=SoilingMethod.STRING_COMPARISON,
        )
    ]
    return Scenario(
        key=key, number=10, title=title,
        story="Soiling is real and measured, but the benefit would last only a few days. Cleaning would cost more than it recovers, so the system declines.",
        injected=injected, interval_minutes=1440, rows=rows,
        metadata=_metadata(key, title, rows, 1440, seed, injected, parameters={"soiling_rate_per_day": 0.00095}),
        evidence=evidence,
        cleaning=demo_cleaning(3.0, 2.0, 5.0, "Illustrative demonstration assumption: natural cleaning expected within days."),
        economics=demo_economics(),
        expected_decision="MONITOR", expected_rule="R6", expected_diagnostic_status="SINGLE_EXPLANATION",
        period_start=DAILY_START, period_end=_day(DAILY_DAYS - 1),
    )


_BUILDERS: dict[str, Callable[[int], Scenario]] = {
    "S01_normal_operation": _s01,
    "S02_confirmed_soiling": _s02,
    "S03_temperature_effect": _s03,
    "S04_inverter_fault": _s04,
    "S05_shading": _s05,
    "S06_curtailment": _s06,
    "S07_missing_data": _s07,
    "S08_conflicting_evidence": _s08,
    "S09_synthetic_demonstration": _s09,
    "S10_unprofitable_cleaning": _s10,
}

SCENARIO_KEYS: tuple[str, ...] = tuple(_BUILDERS)


def build_scenario(key: str, seed: int = DEFAULT_SEED) -> Scenario:
    try:
        builder = _BUILDERS[key]
    except KeyError as exc:
        raise KeyError(f"unknown scenario '{key}'; available: {', '.join(SCENARIO_KEYS)}") from exc
    return builder(seed)


def build_all(seed: int = DEFAULT_SEED) -> list[Scenario]:
    return [build_scenario(key, seed) for key in SCENARIO_KEYS]
