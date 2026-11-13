"""Stateless calculations.  Their results are advisory: nothing is stored and nothing is authorised."""

from __future__ import annotations

from fastapi import APIRouter

from solarwise.api.deps import CurrentUser
from solarwise.api.schemas import EconomicsRequest, EconomicsResponse, EvaluateRequest, EvaluateResponse
from solarwise.core.economics import evaluate_economics
from solarwise.core.models import DeviceSpec
from solarwise.core.pipeline import AnalysisError, AnalysisInput, run_analysis
from solarwise.core.provenance import EvaluationContext
from solarwise.core.recoverable import EnergyRange
from solarwise.ingestion.parser import RawTable
from solarwise.ingestion.validator import validate_table
from solarwise.services.errors import InvalidError

router = APIRouter(tags=["advisory calculations"])

_ECONOMICS_NOTICE = (
    "Arithmetic on the figures supplied in the request. The recoverable energy is taken as given: this result says "
    "nothing about whether soiling is present and is not a cleaning recommendation."
)
_EVALUATE_NOTICE = (
    "Advisory evaluation of data supplied in the request. Nothing was stored, the data were not tied to a registered "
    "plant, and no operational authorisation is issued whatever the outcome."
)


@router.post(
    "/economics/calculate", response_model=EconomicsResponse, summary="Cost-benefit arithmetic for one cleaning",
    description="No price is built in: every cost item and the value of energy must be supplied. Missing inputs are "
                "reported as missing, never assumed.",
)
def calculate_economics(body: EconomicsRequest, _: CurrentUser) -> EconomicsResponse:
    low, base, high = body.recoverable_low_kwh, body.recoverable_base_kwh, body.recoverable_high_kwh
    ordered = [v for v in (low, base, high) if v is not None]
    if ordered != sorted(ordered):
        raise InvalidError("the recoverable-energy estimates must satisfy low <= base <= high")
    result = evaluate_economics(
        EnergyRange(low=low, central=base, high=high),
        body.inputs,
        horizon_days=body.horizon_days,
        recoverable_per_day_central=(base / body.horizon_days) if base is not None and body.horizon_days else None,
        projected_daily_clean_energy_kwh=body.projected_daily_clean_energy_kwh,
        cleaning_effectiveness=body.cleaning_effectiveness,
    )
    return EconomicsResponse(notice=_ECONOMICS_NOTICE, result=result)


@router.post(
    "/recommendations/evaluate", response_model=EvaluateResponse,
    summary="Evaluate a complete case without storing it",
    description="Validates the supplied records exactly like an upload and runs the engine on them. The outcome is "
                "advisory only.",
)
def evaluate(body: EvaluateRequest, user: CurrentUser) -> EvaluateResponse:
    columns: list[str] = []
    for row in body.records:
        for key in row:
            if key not in columns:
                columns.append(key)
    table = RawTable(columns=columns, rows=body.records, file_format="JSON")
    devices = {d.code: DeviceSpec(code=d.code, capacity_kwp=d.capacity_kwp, kind=d.kind) for d in body.devices}
    plant = body.plant
    if user.is_demo:
        plant = plant.model_copy(update={"is_demonstration": True})
    report, parsed = validate_table(table, body.metadata, plant=plant, known_devices=devices)
    if parsed is None or not report.accepted:
        return EvaluateResponse(notice=_EVALUATE_NOTICE, validation=report, result=None)
    context = EvaluationContext.DEMONSTRATION if plant.is_demonstration else EvaluationContext.OPERATIONAL
    try:
        result = run_analysis(
            AnalysisInput(
                plant=plant, observations=parsed.observations, interval_minutes=parsed.interval_minutes,
                channels=parsed.channels, context=context, options=body.options, declared_baseline=parsed.baseline,
                device_observations=parsed.device_observations, devices=devices, device_tag=parsed.device_tag,
                records=[*body.evidence, *parsed.events], dataset_name=body.metadata.name,
                dataset_disclaimer=body.metadata.disclaimer,
                # A case that is not tied to a registered plant and stored dataset is never authorised.
                allow_operational_authorization=False,
            )
        )
    except AnalysisError as exc:
        raise InvalidError(str(exc), code="ANALYSIS_NOT_POSSIBLE") from exc
    return EvaluateResponse(notice=_EVALUATE_NOTICE, validation=report, result=result)
