"""Cleaning economics engine.

    gross benefit   = recoverable energy x energy value
    total cost      = water + labour + equipment + operational + downtime
    net benefit     = gross benefit - total cost
    ROI             = net benefit / total cost x 100
    break-even      = total cost / energy value            [kWh to be recovered]

Three scenarios are evaluated:

* ``CONSERVATIVE``  low recoverable energy, high cost
* ``BASE``          central recoverable energy, central cost
* ``OPTIMISTIC``    high recoverable energy, low cost

No price is built in.  Every monetary input is supplied with the request and
carries a classification (``USER_ASSUMPTION``, ``TECHNICAL_REFERENCE`` or
``OFFICIAL_REFERENCE``) and a source.  A missing cost item is reported as
missing - it is not counted as zero - and the result is then marked
``INCOMPLETE_INPUTS``.

The *basis* of the energy value matters: the price a plant is actually paid
(``SELLING_PRICE``) is not the tariff a consumer pays (``CONSUMER_TARIFF_PROXY``).
A consumer tariff used as a stand-in is accepted for illustration but is not
decision-grade.
"""

from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from solarwise.core.recoverable import Assumption, EnergyRange, RecoverableEnergy, RecoverableStatus


class ValueClassification(StrEnum):
    OFFICIAL_REFERENCE = "OFFICIAL_REFERENCE"
    TECHNICAL_REFERENCE = "TECHNICAL_REFERENCE"
    USER_ASSUMPTION = "USER_ASSUMPTION"


class EnergyValueBasis(StrEnum):
    #: Price the plant actually receives per kWh delivered (PPA, feed-in tariff).
    SELLING_PRICE = "SELLING_PRICE"
    #: Self-consumption: each recovered kWh avoids a purchase at the site's own tariff.
    AVOIDED_PURCHASE_COST = "AVOIDED_PURCHASE_COST"
    #: Internal transfer or planning value set by the operator.
    INTERNAL_VALUATION = "INTERNAL_VALUATION"
    #: A consumer (retail) tariff used as a stand-in for an unknown selling price.
    CONSUMER_TARIFF_PROXY = "CONSUMER_TARIFF_PROXY"


#: Bases on which a cleaning decision may rest.
DECISION_GRADE_BASES = frozenset(
    {EnergyValueBasis.SELLING_PRICE, EnergyValueBasis.AVOIDED_PURCHASE_COST, EnergyValueBasis.INTERNAL_VALUATION}
)


class EconomicInputs(BaseModel):
    """Monetary inputs of one cleaning operation.  ``None`` means *not supplied*."""

    model_config = ConfigDict(extra="forbid")

    currency: str = Field(default="DZD", min_length=3, max_length=3)
    # --- value of energy
    energy_value_per_kwh: float | None = Field(default=None, ge=0)
    energy_value_basis: EnergyValueBasis | None = None
    energy_value_classification: ValueClassification = ValueClassification.USER_ASSUMPTION
    energy_value_source: str | None = Field(default=None, max_length=500)
    # --- water: a total, or volume x unit price
    water_cost: float | None = Field(default=None, ge=0)
    water_volume_m3: float | None = Field(default=None, ge=0)
    water_price_per_m3: float | None = Field(default=None, ge=0)
    # --- labour: a total, or hours x rate
    labour_cost: float | None = Field(default=None, ge=0)
    labour_hours: float | None = Field(default=None, ge=0)
    labour_rate_per_hour: float | None = Field(default=None, ge=0)
    equipment_cost: float | None = Field(default=None, ge=0)
    operational_cost: float | None = Field(default=None, ge=0)
    # --- downtime: a total, or energy not produced during cleaning (valued at the energy value)
    downtime_cost: float | None = Field(default=None, ge=0)
    downtime_energy_kwh: float | None = Field(default=None, ge=0)
    #: Relative spread applied to the total cost for the conservative (+) and optimistic (-) cases [%].
    cost_uncertainty_pct: float | None = Field(default=None, ge=0, le=100)
    cost_classification: ValueClassification = ValueClassification.USER_ASSUMPTION
    cost_source: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _currency_upper(self) -> EconomicInputs:
        if not self.currency.isalpha():
            raise ValueError("currency must be a three-letter ISO 4217 code")
        object.__setattr__(self, "currency", self.currency.upper())
        return self


class CostItem(BaseModel):
    name: str
    amount: float | None
    #: How the amount was obtained: SUPPLIED | COMPUTED | MISSING
    basis: str
    detail: str | None = None


class CostBreakdown(BaseModel):
    items: list[CostItem]
    #: Sum of all items; ``None`` while any item is missing.
    total: float | None
    #: Sum of the items that were supplied (for information only).
    partial_total: float
    missing: list[str]


class ScenarioName(StrEnum):
    CONSERVATIVE = "CONSERVATIVE"
    BASE = "BASE"
    OPTIMISTIC = "OPTIMISTIC"


class ScenarioResult(BaseModel):
    name: ScenarioName
    recoverable_energy_kwh: float | None
    gross_benefit: float | None
    total_cost: float | None
    net_benefit: float | None
    roi_pct: float | None
    profitable: bool | None
    description: str


class EconomicStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE_INPUTS = "INCOMPLETE_INPUTS"
    NO_RECOVERABLE_ENERGY = "NO_RECOVERABLE_ENERGY"


class Verdict(StrEnum):
    #: Net benefit positive even in the conservative case.
    PROFITABLE = "PROFITABLE"
    #: Net benefit positive in the base case, not in the conservative case.
    MARGINAL = "MARGINAL"
    #: Net benefit not positive in the base case.
    UNPROFITABLE = "UNPROFITABLE"
    UNDETERMINED = "UNDETERMINED"


class EconomicsResult(BaseModel):
    status: EconomicStatus
    verdict: Verdict
    currency: str
    energy_value_per_kwh: float | None
    energy_value_basis: EnergyValueBasis | None
    #: The energy value is of a kind a decision may rest on.
    decision_grade: bool
    cost: CostBreakdown
    scenarios: list[ScenarioResult]
    #: Energy that must be recovered for the cleaning to pay for itself [kWh].
    break_even_energy_kwh: float | None
    #: The same, as a soiling loss over the benefit horizon [% of clean energy].
    break_even_soiling_loss_pct: float | None
    #: Days of benefit needed to repay the cleaning at the central recovery rate.
    payback_days: float | None
    horizon_days: float | None
    assumptions: list[Assumption]
    warnings: list[str]
    missing_inputs: list[str]
    formulae: list[str] = Field(
        default_factory=lambda: [
            "gross benefit = recoverable energy x energy value",
            "total cost = water + labour + equipment + operational + downtime",
            "net benefit = gross benefit - total cost",
            "ROI = net benefit / total cost x 100",
            "break-even energy = total cost / energy value",
        ]
    )

    def scenario(self, name: ScenarioName) -> ScenarioResult:
        return next(s for s in self.scenarios if s.name is name)


def _either(
    name: str, total: float | None, quantity: float | None, unit_price: float | None, what: str
) -> CostItem:
    if total is not None:
        return CostItem(name=name, amount=total, basis="SUPPLIED")
    if quantity is not None and unit_price is not None:
        return CostItem(name=name, amount=quantity * unit_price, basis="COMPUTED", detail=f"{quantity:g} {what} x {unit_price:g}")
    return CostItem(name=name, amount=None, basis="MISSING")


def build_costs(inputs: EconomicInputs) -> CostBreakdown:
    """Assemble the cost of one cleaning.  Missing items stay missing."""
    downtime: CostItem
    if inputs.downtime_cost is not None:
        downtime = CostItem(name="downtime", amount=inputs.downtime_cost, basis="SUPPLIED")
    elif inputs.downtime_energy_kwh is not None and inputs.energy_value_per_kwh is not None:
        downtime = CostItem(
            name="downtime",
            amount=inputs.downtime_energy_kwh * inputs.energy_value_per_kwh,
            basis="COMPUTED",
            detail=f"{inputs.downtime_energy_kwh:g} kWh not produced x {inputs.energy_value_per_kwh:g}",
        )
    else:
        downtime = CostItem(name="downtime", amount=None, basis="MISSING")
    items = [
        _either("water", inputs.water_cost, inputs.water_volume_m3, inputs.water_price_per_m3, "m3"),
        _either("labour", inputs.labour_cost, inputs.labour_hours, inputs.labour_rate_per_hour, "h"),
        CostItem(name="equipment", amount=inputs.equipment_cost,
                 basis="SUPPLIED" if inputs.equipment_cost is not None else "MISSING"),
        CostItem(name="operational", amount=inputs.operational_cost,
                 basis="SUPPLIED" if inputs.operational_cost is not None else "MISSING"),
        downtime,
    ]
    missing = [item.name for item in items if item.amount is None]
    partial = math.fsum(item.amount for item in items if item.amount is not None)
    return CostBreakdown(items=items, total=None if missing else partial, partial_total=partial, missing=missing)


def _scenario(
    name: ScenarioName, energy: float | None, value: float | None, cost: float | None, description: str
) -> ScenarioResult:
    gross = energy * value if energy is not None and value is not None else None
    net = gross - cost if gross is not None and cost is not None else None
    roi = net / cost * 100.0 if net is not None and cost is not None and cost > 0 else None
    return ScenarioResult(
        name=name,
        recoverable_energy_kwh=energy,
        gross_benefit=gross,
        total_cost=cost,
        net_benefit=net,
        roi_pct=roi,
        profitable=(net > 0) if net is not None else None,
        description=description,
    )


def evaluate_economics(
    recoverable: EnergyRange,
    inputs: EconomicInputs | None,
    *,
    horizon_days: float | None = None,
    recoverable_per_day_central: float | None = None,
    projected_daily_clean_energy_kwh: float | None = None,
    cleaning_effectiveness: float | None = None,
) -> EconomicsResult:
    """Economics of one cleaning for a given recoverable-energy range."""
    inputs = inputs or EconomicInputs()
    costs = build_costs(inputs)
    value = inputs.energy_value_per_kwh
    warnings: list[str] = []
    missing: list[str] = []

    if value is None:
        missing.append("value of energy per kWh")
    if inputs.energy_value_basis is None:
        missing.append("basis of the energy value (selling price, avoided purchase cost, internal valuation "
                       "or consumer-tariff proxy)")
    missing.extend(f"{name} cost" for name in costs.missing)

    decision_grade = (
        value is not None and inputs.energy_value_basis in DECISION_GRADE_BASES and not costs.missing
    )
    if inputs.energy_value_basis is EnergyValueBasis.CONSUMER_TARIFF_PROXY:
        warnings.append(
            "The energy value is a consumer tariff used as a stand-in. A producer is not paid the consumer "
            "tariff: the figures illustrate an order of magnitude and are not decision-grade. Supply the "
            "price the plant actually receives."
        )
    if costs.missing:
        warnings.append(
            "Cost item(s) not supplied: " + ", ".join(costs.missing) + ". They are NOT counted as zero; "
            "total cost, net benefit and ROI are therefore not stated. Enter 0 explicitly for an item that "
            "does not apply."
        )
    if value is not None and value == 0:
        warnings.append("The energy value is zero: recovered energy has no monetary value in this evaluation.")
    if inputs.energy_value_classification is ValueClassification.USER_ASSUMPTION and value is not None:
        warnings.append("The energy value is a user assumption, not an official or contractual reference.")

    spread = (inputs.cost_uncertainty_pct or 0.0) / 100.0
    if inputs.cost_uncertainty_pct is None and costs.total is not None:
        warnings.append("No cost uncertainty was declared: all three scenarios use the same cost.")
    total = costs.total
    cost_high = total * (1.0 + spread) if total is not None else None
    cost_low = total * (1.0 - spread) if total is not None else None

    scenarios = [
        _scenario(ScenarioName.CONSERVATIVE, recoverable.low, value, cost_high,
                  "Low recoverable energy and high cost."),
        _scenario(ScenarioName.BASE, recoverable.central, value, total, "Central recoverable energy and cost."),
        _scenario(ScenarioName.OPTIMISTIC, recoverable.high, value, cost_low,
                  "High recoverable energy and low cost."),
    ]

    break_even = total / value if total is not None and value is not None and value > 0 else None
    break_even_loss: float | None = None
    if (
        break_even is not None
        and horizon_days
        and projected_daily_clean_energy_kwh
        and cleaning_effectiveness
    ):
        break_even_loss = break_even / (cleaning_effectiveness * projected_daily_clean_energy_kwh * horizon_days) * 100.0
    payback: float | None = None
    if total is not None and value is not None and value > 0 and recoverable_per_day_central:
        payback = total / (recoverable_per_day_central * value)

    no_energy = recoverable.central is None
    if no_energy:
        status = EconomicStatus.NO_RECOVERABLE_ENERGY
        verdict = Verdict.UNDETERMINED
        warnings.append(
            "No recoverable energy is established, so benefit, net benefit and ROI cannot be stated. "
            "The break-even energy shows what a cleaning would have to recover."
        )
    elif missing:
        status = EconomicStatus.INCOMPLETE_INPUTS
        verdict = Verdict.UNDETERMINED
    else:
        status = EconomicStatus.COMPLETE
        conservative, base = scenarios[0], scenarios[1]
        if conservative.profitable:
            verdict = Verdict.PROFITABLE
        elif base.profitable:
            verdict = Verdict.MARGINAL
        else:
            verdict = Verdict.UNPROFITABLE
        if total == 0:
            warnings.append("Total cost is zero: ROI is undefined.")

    assumptions = [
        Assumption(
            name="Energy value", value=value, unit=f"{inputs.currency}/kWh",
            classification=inputs.energy_value_classification.value,
            source=(inputs.energy_value_source or "not stated")
            + (f" [{inputs.energy_value_basis.value}]" if inputs.energy_value_basis else " [basis not declared]"),
        ),
        *[
            Assumption(
                name=f"{item.name.capitalize()} cost", value=item.amount, unit=inputs.currency,
                classification=inputs.cost_classification.value,
                source=(inputs.cost_source or "not stated") + (f" ({item.detail})" if item.detail else ""),
            )
            for item in costs.items
        ],
    ]
    if inputs.cost_uncertainty_pct is not None:
        assumptions.append(
            Assumption(name="Cost uncertainty", value=inputs.cost_uncertainty_pct, unit="%",
                       classification="USER_ASSUMPTION", source=inputs.cost_source or "not stated")
        )

    return EconomicsResult(
        status=status,
        verdict=verdict,
        currency=inputs.currency,
        energy_value_per_kwh=value,
        energy_value_basis=inputs.energy_value_basis,
        decision_grade=decision_grade and status is EconomicStatus.COMPLETE,
        cost=costs,
        scenarios=scenarios,
        break_even_energy_kwh=break_even,
        break_even_soiling_loss_pct=break_even_loss,
        payback_days=payback,
        horizon_days=horizon_days,
        assumptions=assumptions,
        warnings=warnings,
        missing_inputs=missing,
    )


def evaluate_cleaning_economics(
    recoverable: RecoverableEnergy, inputs: EconomicInputs | None, *, cleaning_effectiveness: float | None
) -> EconomicsResult:
    """Economics for the output of the recoverable-energy engine."""
    energy = recoverable.recoverable if recoverable.status is RecoverableStatus.ESTIMATED else EnergyRange()
    return evaluate_economics(
        energy,
        inputs,
        horizon_days=recoverable.horizon_days,
        recoverable_per_day_central=recoverable.recoverable_per_day.central,
        projected_daily_clean_energy_kwh=(
            recoverable.projected_daily_clean_energy.value if recoverable.projected_daily_clean_energy else None
        ),
        cleaning_effectiveness=cleaning_effectiveness,
    )
