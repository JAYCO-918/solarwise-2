"""Hand-built analysis inputs for tests.

These cases are constructed directly (not through the demo generator), with
exact, noise-free numbers, so that the expected results can be worked out by
hand.  Unless stated otherwise the data are tagged as *measured* on a
non-demonstration plant in the operational context - the only situation in
which an operational CLEAN_NOW is possible at all.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from solarwise.core.economics import EconomicInputs, EnergyValueBasis
from solarwise.core.models import (
    BaselineDescriptor,
    BaselineMethod,
    ChannelMeta,
    EvidenceRecord,
    MeteringBoundary,
    Metric,
    Observation,
    PlantSpec,
    SoilingMethod,
)
from solarwise.core.pipeline import AnalysisInput, AnalysisOptions
from solarwise.core.provenance import EvaluationContext, ProvenanceTag, measured, modelled
from solarwise.core.recoverable import CleaningAssumptions

ZONE = ZoneInfo("Africa/Algiers")
START = date(2026, 5, 1)
#: Expected energy of every day of a hand-built case [kWh].
DAILY_EXPECTED_KWH = 50_000.0

PLANT = PlantSpec(
    name="Test plant",
    capacity_dc_kwp=10_000.0,
    capacity_ac_kw=8_500.0,
    latitude=33.5,
    longitude=6.8,
    timezone="Africa/Algiers",
    tilt_deg=30.0,
    module_temp_coeff_per_c=-0.0035,
    system_loss_fraction=0.14,
)

Series = float | Callable[[int], float] | None


def _value(series: Series, index: int) -> float | None:
    if series is None:
        return None
    return series(index) if callable(series) else float(series)


def midnight_utc(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=ZONE).astimezone(UTC)


def cleaning_assumptions(horizon: float = 30.0) -> CleaningAssumptions:
    return CleaningAssumptions(
        cleaning_effectiveness=0.9,
        cleaning_effectiveness_low=0.8,
        cleaning_effectiveness_high=1.0,
        benefit_horizon_days=horizon,
        benefit_horizon_days_low=horizon * 0.8,
        benefit_horizon_days_high=horizon * 1.2,
        source_note="test assumption",
    )


def economic_inputs(**overrides: object) -> EconomicInputs:
    values: dict[str, object] = {
        "currency": "DZD",
        "energy_value_per_kwh": 5.0,
        "energy_value_basis": EnergyValueBasis.SELLING_PRICE,
        "energy_value_source": "test assumption",
        "water_cost": 10_000.0,
        "labour_cost": 60_000.0,
        "equipment_cost": 20_000.0,
        "operational_cost": 10_000.0,
        "downtime_cost": 0.0,
        "cost_uncertainty_pct": 20.0,
    }
    values.update(overrides)
    return EconomicInputs.model_validate(values)


def make_case(
    *,
    days: int = 30,
    start: date = START,
    true_soiling_ratio: Series = 1.0,
    reported_soiling_ratio: Series = None,
    availability: Series = 1.0,
    log_availability: bool = True,
    extra_loss_fraction: Series = 0.0,
    actual_tag: ProvenanceTag | None = None,
    expected_tag: ProvenanceTag | None = None,
    soiling_tag: ProvenanceTag | None = None,
    soiling_method: SoilingMethod | None = SoilingMethod.SOILING_STATION,
    soiling_uncertainty_abs: float | None = 0.005,
    declare_uncertainty: bool = True,
    missing_actual_days: Iterable[int] = (),
    absent_days: Iterable[int] = (),
    records: Sequence[EvidenceRecord] = (),
    context: EvaluationContext = EvaluationContext.OPERATIONAL,
    plant: PlantSpec = PLANT,
    cleaning: CleaningAssumptions | str | None = "default",
    economics: EconomicInputs | str | None = "default",
    baseline: BaselineDescriptor | str | None = "default",
    expected_kwh: float = DAILY_EXPECTED_KWH,
) -> AnalysisInput:
    """Daily case: ``actual = expected x soiling x availability x (1 - extra loss)``."""
    missing = set(missing_actual_days)
    absent = set(absent_days)
    observations: list[Observation] = []
    for index in range(days):
        if index in absent:
            continue
        soiling = _value(true_soiling_ratio, index)
        avail = _value(availability, index)
        extra = _value(extra_loss_fraction, index) or 0.0
        actual = expected_kwh * (soiling if soiling is not None else 1.0) * (avail if avail is not None else 1.0)
        actual *= 1.0 - extra
        observations.append(
            Observation(
                start_utc=midnight_utc(start + timedelta(days=index)),
                actual_energy_kwh=None if index in missing else actual,
                expected_energy_kwh=expected_kwh,
                availability_fraction=avail if log_availability else None,
                soiling_ratio=_value(reported_soiling_ratio, index),
            )
        )
    channels: dict[Metric, ChannelMeta] = {
        Metric.ACTUAL_ENERGY: ChannelMeta(
            metric=Metric.ACTUAL_ENERGY, tag=actual_tag or measured("revenue meter"), unit="kWh",
            uncertainty_pct=0.5 if declare_uncertainty else None, boundary=MeteringBoundary.GRID_METER,
        ),
        Metric.EXPECTED_ENERGY: ChannelMeta(
            metric=Metric.EXPECTED_ENERGY, tag=expected_tag or modelled("performance model"), unit="kWh",
            uncertainty_pct=2.0 if declare_uncertainty else None, boundary=MeteringBoundary.GRID_METER,
        ),
    }
    if log_availability:
        channels[Metric.AVAILABILITY] = ChannelMeta(
            metric=Metric.AVAILABILITY, tag=measured("SCADA availability log"), unit="fraction"
        )
    if reported_soiling_ratio is not None:
        channels[Metric.SOILING_RATIO] = ChannelMeta(
            metric=Metric.SOILING_RATIO, tag=soiling_tag or measured("soiling station"), unit="fraction",
            uncertainty_abs=soiling_uncertainty_abs, soiling_method=soiling_method,
        )
    descriptor: BaselineDescriptor | None
    if baseline == "default":
        descriptor = BaselineDescriptor(
            method=BaselineMethod.TELEMETRY_MODEL, irradiance_adjusted=True, temperature_adjusted=True,
            degradation_adjusted=True, soiling_allowance_fraction=0.0,
        )
    else:
        assert baseline is None or isinstance(baseline, BaselineDescriptor)
        descriptor = baseline
    assert cleaning is None or cleaning == "default" or isinstance(cleaning, CleaningAssumptions)
    assert economics is None or economics == "default" or isinstance(economics, EconomicInputs)
    return AnalysisInput(
        plant=plant,
        observations=observations,
        interval_minutes=1440,
        channels=channels,
        context=context,
        options=AnalysisOptions(
            cleaning=cleaning_assumptions() if cleaning == "default" else cleaning,  # type: ignore[arg-type]
            economics=economic_inputs() if economics == "default" else economics,  # type: ignore[arg-type]
        ),
        declared_baseline=descriptor,
        records=records,
        dataset_name="hand-built test case",
    )


def soiled_case(loss: float = 0.08, **kwargs: object) -> AnalysisInput:
    """A plant uniformly soiled by ``loss`` with a soiling station that reports it."""
    params: dict[str, object] = {"true_soiling_ratio": 1.0 - loss, "reported_soiling_ratio": 1.0 - loss}
    params.update(kwargs)
    return make_case(**params)  # type: ignore[arg-type]
