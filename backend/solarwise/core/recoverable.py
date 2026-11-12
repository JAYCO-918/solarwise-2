"""Recoverable-energy engine.

Four quantities are kept strictly apart:

``observed gap``
    Expected minus actual energy.  A fact about production, silent on causes.
``soiling-related loss``
    The part of the loss that a *soiling measurement* accounts for.  It exists
    only when soiling was measured; it is never backed out of the gap.
``recoverable energy``
    Energy that cleaning is expected to bring back over the period during which
    the cleaning keeps its benefit.  A projection, built on the measured loss
    and on declared assumptions.
``uncertainty``
    A low / central / high range, traceable to the declared measurement
    uncertainty and to the declared range of each assumption.

Method
------
With current soiling loss fraction ``L`` (measured), cleaning effectiveness
``eta`` (share of the soiling loss removed), projected daily energy of a clean
array ``E_d`` and benefit horizon ``H`` (days until rain or the next scheduled
cleaning would have reset the array anyway):

    recoverable = L x eta x E_d x H

Soiled and cleaned arrays are assumed to keep accumulating dust at the same
rate, so the advantage of the cleaned array stays ``L x eta`` until the horizon.

Without a credible, quantified soiling measurement the engine returns
``INSUFFICIENT_EVIDENCE`` and no number.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from solarwise.core.attribution import LossAttribution
from solarwise.core.diagnostics import SoilingEvidence
from solarwise.core.gap import GapSeries
from solarwise.core.models import AnalysisThresholds
from solarwise.core.provenance import UNKNOWN_TAG, ProvenanceTag, Traced, derive, modelled


class RecoverableStatus(StrEnum):
    ESTIMATED = "ESTIMATED"
    #: No credible, quantified soiling measurement: nothing can be said.
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    #: Soiling is credibly measured but an assumption needed for the projection is missing.
    MISSING_ASSUMPTIONS = "MISSING_ASSUMPTIONS"
    #: The measurement shows a (near-)clean array: there is nothing to recover.
    NO_RECOVERABLE_LOSS = "NO_RECOVERABLE_LOSS"


class CleaningAssumptions(BaseModel):
    """Assumptions about the effect of a cleaning.  None of them has a default.

    They are the user's assumptions about the site and the cleaning method and
    are reported as such.
    """

    model_config = ConfigDict(extra="forbid")

    #: Share of the soiling loss removed by the cleaning (1 = back to clean).
    cleaning_effectiveness: float | None = Field(default=None, gt=0, le=1)
    cleaning_effectiveness_low: float | None = Field(default=None, gt=0, le=1)
    cleaning_effectiveness_high: float | None = Field(default=None, gt=0, le=1)
    #: Days during which the cleaning keeps its benefit.
    benefit_horizon_days: float | None = Field(default=None, gt=0, le=366)
    benefit_horizon_days_low: float | None = Field(default=None, gt=0, le=366)
    benefit_horizon_days_high: float | None = Field(default=None, gt=0, le=366)
    #: Expected daily energy of the clean array over the horizon [kWh/day].
    #: When omitted, the mean of the assessment window is projected forward.
    projected_daily_clean_energy_kwh: float | None = Field(default=None, gt=0)
    source_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _ordered(self) -> CleaningAssumptions:
        for name in ("cleaning_effectiveness", "benefit_horizon_days"):
            low, mid, high = getattr(self, f"{name}_low"), getattr(self, name), getattr(self, f"{name}_high")
            if (low is not None or high is not None) and mid is None:
                raise ValueError(f"{name}: a range was given without a central value")
            if low is not None and mid is not None and low > mid:
                raise ValueError(f"{name}_low exceeds the central value")
            if high is not None and mid is not None and high < mid:
                raise ValueError(f"{name}_high is below the central value")
        return self


class Assumption(BaseModel):
    name: str
    value: float | None
    unit: str
    #: USER_ASSUMPTION | TECHNICAL_REFERENCE | OFFICIAL_REFERENCE | DERIVED_FROM_DATA
    classification: str
    source: str


class EnergyRange(BaseModel):
    low: float | None = None
    central: float | None = None
    high: float | None = None
    unit: str = "kWh"


class RecoverableEnergy(BaseModel):
    status: RecoverableStatus
    reasons: list[str] = Field(default_factory=list)
    # --- the four separate quantities
    observed_gap: Traced
    observed_gap_pct: float | None
    soiling_related_loss: Traced
    soiling_loss_pct: float | None = None
    soiling_loss_low_pct: float | None = None
    soiling_loss_high_pct: float | None = None
    #: Loss in the assessment window that is not attributed to any quantified factor.
    unexplained_loss: Traced
    recoverable: EnergyRange = Field(default_factory=EnergyRange)
    recoverable_tag: ProvenanceTag = UNKNOWN_TAG
    recoverable_per_day: EnergyRange = Field(default_factory=EnergyRange)
    #: Soiling loss that remains after the cleaning (central case) [% of clean energy].
    residual_soiling_after_cleaning_pct: float | None = None
    # --- projection
    horizon_days: float | None = None
    projected_daily_clean_energy: Traced | None = None
    assumptions: list[Assumption] = Field(default_factory=list)
    uncertainty_statement: str = ""
    method: str = "recoverable = soiling loss fraction x cleaning effectiveness x projected daily clean energy x horizon"
    #: True only for an estimate that rests on a credible, measured-class soiling measurement.
    usable_for_decision: bool = False
    warnings: list[str] = Field(default_factory=list)


def estimate_recoverable_energy(
    *,
    gap: GapSeries,
    attribution: LossAttribution,
    soiling: SoilingEvidence,
    assumptions: CleaningAssumptions | None,
    thresholds: AnalysisThresholds,
) -> RecoverableEnergy:
    """Project the energy a cleaning would recover, or say why that cannot be done."""
    window = attribution.window
    k = thresholds.coverage_factor

    observed_gap = Traced(
        value=gap.window.result.gap_kwh,
        unit="kWh",
        tag=gap.gap.tag,
        basis="expected - actual over the assessment window",
    )
    unexplained = Traced(
        value=window.residual_kwh,
        unit="kWh",
        tag=derive([gap.expected.tag, gap.actual.tag], source="SolarWise attribution",
                   method="expected - quantified factors - actual", model_applied=True),
        basis="residual of the factor chain over the assessment window",
    )
    no_soiling = Traced(value=None, unit="kWh", tag=UNKNOWN_TAG, basis="no soiling measurement")

    def result(status: RecoverableStatus, reasons: list[str], **extra: Any) -> RecoverableEnergy:
        return RecoverableEnergy(
            status=status,
            reasons=reasons,
            observed_gap=observed_gap,
            observed_gap_pct=gap.window.result.relative_gap_pct,
            unexplained_loss=unexplained,
            **extra,
        )

    # ------------------------------------------------------------------ evidence gate
    if not soiling.available or soiling.loss_pct is None or soiling.tag is None:
        return result(
            RecoverableStatus.INSUFFICIENT_EVIDENCE,
            [
                "No quantified soiling measurement is available. The production gap alone does not show "
                "how much of the loss - if any - is soiling, so no recoverable energy is stated."
            ],
            soiling_related_loss=no_soiling,
        )

    u = soiling.std_uncertainty_pct
    loss = soiling.loss_pct
    loss_low = max(0.0, loss - k * u) if u is not None else loss
    loss_high = loss + k * u if u is not None else loss

    soiling_contribution = next((c for c in window.contributions if c.factor.value == "SOILING"), None)
    soiling_loss_kwh = soiling_contribution.energy.value if soiling_contribution is not None else None
    if soiling_loss_kwh is None and window.pre_soiling_expected_kwh is not None:
        soiling_loss_kwh = window.pre_soiling_expected_kwh * loss / 100.0
    soiling_related = Traced(
        value=soiling_loss_kwh,
        unit="kWh",
        tag=derive([soiling.tag, gap.expected.tag], source="SolarWise attribution",
                   method="pre-soiling expected energy x (1 - soiling ratio)"),
        std_uncertainty=(
            window.pre_soiling_expected_kwh * u / 100.0
            if u is not None and window.pre_soiling_expected_kwh is not None
            else None
        ),
        basis="measured soiling ratio applied to the assessment window",
    )
    common: dict[str, Any] = {
        "soiling_related_loss": soiling_related,
        "soiling_loss_pct": loss,
        "soiling_loss_low_pct": loss_low,
        "soiling_loss_high_pct": loss_high,
    }

    if not soiling.credible:
        if soiling.measured_class and soiling.recent and not soiling.above_floor:
            return result(
                RecoverableStatus.NO_RECOVERABLE_LOSS,
                [
                    f"The soiling measurement shows a loss of {loss:.1f} %, which is not distinguishable from "
                    "a clean array. Cleaning has nothing material to recover."
                ],
                **common,
            )
        return result(
            RecoverableStatus.INSUFFICIENT_EVIDENCE,
            ["A soiling figure exists but is not credible measured evidence:", *soiling.notes],
            **common,
        )

    # ------------------------------------------------------------------ assumptions
    a = assumptions or CleaningAssumptions()
    missing: list[str] = []
    if a.cleaning_effectiveness is None:
        missing.append("cleaning effectiveness (share of the soiling loss the cleaning removes)")
    if a.benefit_horizon_days is None:
        missing.append("benefit horizon (days until rain or the next scheduled cleaning)")

    if a.projected_daily_clean_energy_kwh is not None:
        daily_energy = a.projected_daily_clean_energy_kwh
        projected = Traced(
            value=daily_energy,
            unit="kWh/day",
            tag=modelled("user-supplied projection", "forecast of clean-array energy supplied with the request"),
            basis="USER_ASSUMPTION",
        )
        daily_class, daily_source = "USER_ASSUMPTION", "supplied with the request"
    else:
        days = max(1, (window.end - window.start).days + 1)
        covered_days = len({d.day for d in attribution.daily if d.day >= window.start and d.pre_soiling_expected_kwh})
        if window.pre_soiling_expected_kwh is None or covered_days == 0:
            daily_energy = None
            projected = None
            missing.append("projected daily energy of the clean array (no expected energy in the assessment window)")
        else:
            daily_energy = window.pre_soiling_expected_kwh / covered_days
            projected = Traced(
                value=daily_energy,
                unit="kWh/day",
                tag=derive([gap.expected.tag], source="SolarWise projection",
                           method="mean daily pre-soiling expected energy of the assessment window, held constant",
                           model_applied=True),
                basis="PERSISTENCE_ASSUMPTION",
                note=f"Mean of {covered_days} day(s) in a {days}-day window; assumes the coming weeks resemble it.",
            )
        daily_class, daily_source = "DERIVED_FROM_DATA", "mean of the assessment window (persistence assumption)"

    if missing:
        return result(
            RecoverableStatus.MISSING_ASSUMPTIONS,
            ["Soiling is credibly measured, but the projection needs: " + "; ".join(missing) + "."],
            projected_daily_clean_energy=projected,
            **common,
        )
    assert a.cleaning_effectiveness is not None and a.benefit_horizon_days is not None and daily_energy is not None

    eta = a.cleaning_effectiveness
    eta_low = a.cleaning_effectiveness_low if a.cleaning_effectiveness_low is not None else eta
    eta_high = a.cleaning_effectiveness_high if a.cleaning_effectiveness_high is not None else eta
    horizon = a.benefit_horizon_days
    horizon_low = a.benefit_horizon_days_low if a.benefit_horizon_days_low is not None else horizon
    horizon_high = a.benefit_horizon_days_high if a.benefit_horizon_days_high is not None else horizon

    # Conservative case: never credit more soiling than production itself shows.
    warnings: list[str] = []
    conservative_loss = loss_low
    gap_to_explain = soiling.gap_to_explain_pct
    if gap_to_explain is not None and gap_to_explain < conservative_loss:
        conservative_loss = max(0.0, gap_to_explain)
        warnings.append(
            f"Conservative case limited to the deviation actually seen in production ({gap_to_explain:.1f} %), "
            f"which is lower than the lower bound of the measured soiling loss ({loss_low:.1f} %)."
        )

    per_day = EnergyRange(
        low=conservative_loss / 100.0 * eta_low * daily_energy,
        central=loss / 100.0 * eta * daily_energy,
        high=loss_high / 100.0 * eta_high * daily_energy,
        unit="kWh/day",
    )
    assert per_day.low is not None and per_day.central is not None and per_day.high is not None
    recoverable = EnergyRange(
        low=per_day.low * horizon_low,
        central=per_day.central * horizon,
        high=per_day.high * horizon_high,
    )

    statement_parts = []
    if u is not None:
        statement_parts.append(
            f"soiling loss {loss:.1f} % with declared standard uncertainty {u:.1f} % points "
            f"(range {loss_low:.1f} .. {loss_high:.1f} % at k = {k:g})"
        )
    else:
        statement_parts.append(
            f"soiling loss {loss:.1f} % with NO declared measurement uncertainty (not propagated)"
        )
        warnings.append(
            "The soiling measurement has no declared uncertainty: the low/high range reflects the assumptions only."
        )
    if eta_low == eta_high:
        statement_parts.append(f"cleaning effectiveness {eta:.2f} (no range supplied)")
        warnings.append("No range was supplied for cleaning effectiveness.")
    else:
        statement_parts.append(f"cleaning effectiveness {eta_low:.2f} .. {eta_high:.2f}")
    if horizon_low == horizon_high:
        statement_parts.append(f"benefit horizon {horizon:g} days (no range supplied)")
    else:
        statement_parts.append(f"benefit horizon {horizon_low:g} .. {horizon_high:g} days")
    statement = (
        "Range obtained by combining the extremes of: " + "; ".join(statement_parts) + ". It is a scenario "
        "range, not a statistical confidence interval. Not included: weather over the horizon differing from "
        "the projection, a change of soiling rate, and how representative the soiling sensor is of the array."
    )

    listed = [
        Assumption(name="Measured soiling loss", value=loss, unit="%", classification="DERIVED_FROM_DATA",
                   source=f"{soiling.reference or 'soiling measurement'} [{soiling.tag.label}]"),
        Assumption(name="Cleaning effectiveness", value=eta, unit="fraction", classification="USER_ASSUMPTION",
                   source=a.source_note or "supplied with the request"),
        Assumption(name="Benefit horizon", value=horizon, unit="days", classification="USER_ASSUMPTION",
                   source=a.source_note or "supplied with the request"),
        Assumption(name="Projected daily energy of the clean array", value=daily_energy, unit="kWh/day",
                   classification=daily_class, source=daily_source),
    ]
    tag = derive(
        [soiling.tag, gap.expected.tag],
        source="SolarWise recoverable-energy engine",
        method="measured soiling loss x assumed cleaning effectiveness x projected clean energy x assumed horizon",
        model_applied=True,
    )
    return result(
        RecoverableStatus.ESTIMATED,
        ["Projection based on a credible soiling measurement and the declared assumptions."],
        recoverable=recoverable,
        recoverable_tag=tag,
        recoverable_per_day=per_day,
        residual_soiling_after_cleaning_pct=loss * (1.0 - eta),
        horizon_days=horizon,
        projected_daily_clean_energy=projected,
        assumptions=listed,
        uncertainty_statement=statement,
        usable_for_decision=True,
        warnings=warnings,
        **common,
    )
