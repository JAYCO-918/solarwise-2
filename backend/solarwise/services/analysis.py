"""Running the engine on stored data and keeping what it concluded."""

from __future__ import annotations

from sqlalchemy import ColumnElement, or_, select, true
from sqlalchemy.orm import Session

from solarwise.core.baseline import PvgisMonth
from solarwise.core.models import BaselineMethod, ChannelMeta, Metric, Observation
from solarwise.core.pipeline import AnalysisError, AnalysisInput, AnalysisOptions, AnalysisResult, run_analysis
from solarwise.core.provenance import EvaluationContext
from solarwise.db.models import Analysis, Dataset, DatasetKind, Plant, User
from solarwise.services import datasets as dataset_service
from solarwise.services import evidence as evidence_service
from solarwise.services import plants as plant_service
from solarwise.services.errors import InvalidError, NotFoundError

#: Analyses kept per plant for a demonstration account (older ones are pruned).
DEMO_ANALYSES_KEPT = 60


def evaluation_context(user: User | None, plant: Plant) -> EvaluationContext:
    """The context is decided here, on the server, never by the client.

    A demonstration plant, or anything evaluated from a demonstration session,
    is a demonstration: its decisions are simulations.
    """
    if plant.is_demonstration or (user is not None and user.is_demo):
        return EvaluationContext.DEMONSTRATION
    return EvaluationContext.OPERATIONAL


def _merge_weather(
    primary: list[Observation], channels: dict[Metric, ChannelMeta], weather_dataset: Dataset, db: Session
) -> list[str]:
    """Fill weather channels the production dataset lacks from a weather dataset of the same plant."""
    extra_channels = dataset_service.channels_of(weather_dataset)
    weather = {o.start_utc: o for o in dataset_service.load_observations(db, weather_dataset).observations}
    added: list[str] = []
    for metric, meta in extra_channels.items():
        if metric in channels or metric not in _WEATHER_METRICS:
            continue
        column = _WEATHER_METRICS[metric]
        used = False
        for obs in primary:
            source = weather.get(obs.start_utc)
            if source is not None and getattr(source, column) is not None:
                setattr(obs, column, getattr(source, column))
                used = True
        if used:
            channels[metric] = meta
            added.append(column)
    return added


_WEATHER_METRICS: dict[Metric, str] = {
    Metric.POA_IRRADIATION: "poa_irradiation_kwh_m2",
    Metric.GHI: "ghi_kwh_m2",
    Metric.AMBIENT_TEMP: "ambient_temp_c",
    Metric.MODULE_TEMP: "module_temp_c",
    Metric.WIND_SPEED: "wind_speed_ms",
    Metric.RELATIVE_HUMIDITY: "relative_humidity_pct",
    Metric.PRECIPITATION: "precipitation_mm",
}


def build_input(
    db: Session,
    user: User | None,
    plant: Plant,
    dataset: Dataset,
    options: AnalysisOptions,
    weather_dataset: Dataset | None = None,
) -> AnalysisInput:
    if dataset.kind != DatasetKind.PRODUCTION.value:
        raise InvalidError("a weather-only dataset cannot be analysed on its own: it contains no production",
                           code="NOT_A_PRODUCTION_DATASET")
    loaded = dataset_service.load_observations(db, dataset)
    channels = dataset_service.channels_of(dataset)
    if weather_dataset is not None:
        if weather_dataset.plant_id != plant.id:
            raise NotFoundError("weather dataset not found")
        if weather_dataset.interval_minutes != dataset.interval_minutes:
            raise InvalidError(
                f"the weather dataset has {weather_dataset.interval_minutes}-minute intervals, the production "
                f"dataset {dataset.interval_minutes}-minute intervals: they cannot be combined",
                code="INTERVAL_MISMATCH",
            )
        _merge_weather(loaded.observations, channels, weather_dataset, db)

    request = options.baseline
    if request.method == BaselineMethod.PVGIS_TYPICAL_YEAR and not request.pvgis_monthly and plant.pvgis_monthly:
        request = request.model_copy(
            update={
                "pvgis_monthly": [PvgisMonth.model_validate(m) for m in plant.pvgis_monthly],
                "pvgis_source": plant.pvgis_source,
            }
        )
        options = options.model_copy(update={"baseline": request})

    return AnalysisInput(
        plant=plant_service.spec_of(plant),
        observations=loaded.observations,
        interval_minutes=dataset.interval_minutes,
        channels=channels,
        context=evaluation_context(user, plant),
        options=options,
        declared_baseline=dataset_service.baseline_of(dataset),
        device_observations=loaded.device_observations,
        devices=plant_service.device_specs(db, plant),
        device_tag=dataset_service.device_tag_of(dataset),
        records=evidence_service.records_for(db, plant, dataset),
        import_issues=dataset_service.import_issues_of(dataset),
        dataset_name=dataset.name,
        dataset_disclaimer=dataset.declared_metadata.get("disclaimer"),
    )


def run_and_store(
    db: Session,
    user: User | None,
    plant: Plant,
    dataset: Dataset,
    options: AnalysisOptions,
    weather_dataset: Dataset | None = None,
) -> tuple[Analysis, AnalysisResult]:
    inp = build_input(db, user, plant, dataset, options, weather_dataset)
    try:
        result = run_analysis(inp)
    except AnalysisError as exc:
        raise InvalidError(str(exc), code="ANALYSIS_NOT_POSSIBLE") from exc
    rec = result.recommendation
    analysis = Analysis(
        plant_id=plant.id,
        dataset_id=dataset.id,
        weather_dataset_id=weather_dataset.id if weather_dataset is not None else None,
        created_by_id=user.id if user is not None else None,
        engine_version=result.engine_version,
        context=result.context.value,
        period_start=result.period_start,
        period_end=result.period_end,
        decision=rec.decision.value,
        rule=rec.rule,
        reason_code=rec.reason_code.value,
        diagnostic_status=result.diagnostics.status.value,
        simulated=rec.simulated,
        operational_authorization=rec.operational_authorization,
        gap_pct=result.gap.result.relative_gap_pct,
        window_gap_pct=result.gap.window.result.relative_gap_pct,
        headline=rec.headline,
        options=options.model_dump(mode="json"),
        result=result.model_dump(mode="json"),
    )
    db.add(analysis)
    db.flush()
    if user is not None and user.is_demo:
        _prune_demo_analyses(db, plant, user)
    return analysis, result


def _prune_demo_analyses(db: Session, plant: Plant, user: User) -> None:
    stale = db.scalars(
        select(Analysis)
        .where(Analysis.plant_id == plant.id, Analysis.created_by_id == user.id)
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .offset(DEMO_ANALYSES_KEPT)
    )
    for analysis in stale:
        db.delete(analysis)


def _visible_to(user: User) -> ColumnElement[bool]:
    """A demonstration visitor sees the analyses shipped with the demonstration and their own - nobody else's."""
    if user.is_demo:
        return or_(Analysis.created_by_id.is_(None), Analysis.created_by_id == user.id)
    return true()


def get_analysis(db: Session, user: User, analysis_id: int) -> tuple[Analysis, Plant]:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None or (user.is_demo and analysis.created_by_id not in (None, user.id)):
        raise NotFoundError("analysis not found")
    try:
        plant = plant_service.get_plant(db, user, analysis.plant_id)
    except NotFoundError as exc:
        raise NotFoundError("analysis not found") from exc
    return analysis, plant


def stored_result(analysis: Analysis) -> AnalysisResult:
    return AnalysisResult.model_validate(analysis.result)


def list_analyses(
    db: Session, user: User, plant: Plant, *, dataset_id: int | None = None, limit: int = 50, offset: int = 0
) -> list[Analysis]:
    query = select(Analysis).where(Analysis.plant_id == plant.id, _visible_to(user))
    if dataset_id is not None:
        query = query.where(Analysis.dataset_id == dataset_id)
    return list(db.scalars(query.order_by(Analysis.created_at.desc(), Analysis.id.desc()).limit(limit).offset(offset)))


def latest_by_dataset(db: Session, user: User, plant: Plant) -> dict[int, Analysis]:
    """The most recent visible analysis of each dataset of the plant."""
    latest: dict[int, Analysis] = {}
    for analysis in db.scalars(
        select(Analysis).where(Analysis.plant_id == plant.id, _visible_to(user))
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
    ):
        latest.setdefault(analysis.dataset_id, analysis)
    return latest


def latest_for_plant(db: Session, user: User, plant: Plant) -> Analysis | None:
    return db.scalar(
        select(Analysis).where(Analysis.plant_id == plant.id, _visible_to(user))
        .order_by(Analysis.created_at.desc(), Analysis.id.desc()).limit(1)
    )
