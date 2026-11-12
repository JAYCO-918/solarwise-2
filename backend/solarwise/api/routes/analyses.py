"""Analyses: run the engine on a stored dataset, read results, export reports."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request, Response

from solarwise.ai import AiExplanation, build_provider, explain
from solarwise.api.deps import AppSettings, CurrentUser, DbSession, client_address
from solarwise.api.schemas import AnalysisDetail, AnalysisRequest, AnalysisSummary, ForecastResponse
from solarwise.core.forecast import MAX_HORIZON_DAYS, forecast_performance_index
from solarwise.core.pipeline import AnalysisOptions
from solarwise.db.models import Analysis, Dataset, Role, User
from solarwise.reports import ReportMeta, build_document, render_csv, render_html, render_json, render_pdf
from solarwise.security import AttemptLimiter
from solarwise.services import analysis as analysis_service
from solarwise.services import audit
from solarwise.services import datasets as dataset_service
from solarwise.services import plants as plant_service
from solarwise.services.errors import ForbiddenError, NotFoundError

router = APIRouter(tags=["analyses"])


def _detail(db: DbSession, analysis: Analysis) -> AnalysisDetail:
    dataset = db.get(Dataset, analysis.dataset_id)
    return AnalysisDetail(
        **AnalysisSummary.of(analysis).model_dump(),
        dataset_name=dataset.name if dataset is not None else "",
        dataset_sha256=dataset.content_sha256 if dataset is not None else "",
        options=AnalysisOptions.model_validate(analysis.options),
        result=analysis_service.stored_result(analysis),
    )


@router.post(
    "/datasets/{dataset_id}/analyses", response_model=AnalysisDetail, status_code=201,
    summary="Run an analysis",
    description="Runs the deterministic engine on the stored dataset with the supplied assumptions and keeps the "
                "complete result. Whether the result is a demonstration is decided by the server, never by the request.",
)
def run_analysis(dataset_id: int, body: AnalysisRequest, user: CurrentUser, db: DbSession, request: Request) -> AnalysisDetail:
    dataset, plant = dataset_service.get_dataset(db, user, dataset_id)
    if user.role == Role.VIEWER.value:
        raise ForbiddenError("your account is read-only")
    weather = None
    if body.weather_dataset_id is not None:
        weather, weather_plant = dataset_service.get_dataset(db, user, body.weather_dataset_id)
        if weather_plant.id != plant.id:
            raise NotFoundError("weather dataset not found")
    analysis, _ = analysis_service.run_and_store(db, user, plant, dataset, body.options, weather)
    audit.record(db, "ANALYSIS_RUN", user=user, entity="analysis", entity_id=analysis.id,
                 detail={"dataset_id": dataset.id, "decision": analysis.decision, "rule": analysis.rule,
                         "simulated": analysis.simulated}, remote_address=client_address(request))
    return _detail(db, analysis)


@router.get("/plants/{plant_id}/analyses", response_model=list[AnalysisSummary], summary="Analyses of a plant")
def list_analyses(
    plant_id: int, user: CurrentUser, db: DbSession, dataset_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
) -> list[AnalysisSummary]:
    plant = plant_service.get_plant(db, user, plant_id)
    return [
        AnalysisSummary.of(a)
        for a in analysis_service.list_analyses(db, user, plant, dataset_id=dataset_id, limit=limit, offset=offset)
    ]


@router.get("/analyses/{analysis_id}", response_model=AnalysisDetail, summary="One analysis, exactly as it was issued")
def get_analysis(analysis_id: int, user: CurrentUser, db: DbSession) -> AnalysisDetail:
    analysis, _ = analysis_service.get_analysis(db, user, analysis_id)
    return _detail(db, analysis)


@router.post(
    "/analyses/{analysis_id}/explanation", response_model=AiExplanation,
    summary="Plain-language explanation",
    description="Returns the engine's own explanation. When a language model is configured it is asked to rephrase "
                "that explanation; its answer is shown only if it passes every check against the engine's output.",
)
def explanation(analysis_id: int, user: CurrentUser, db: DbSession, settings: AppSettings, request: Request) -> AiExplanation:
    analysis, _ = analysis_service.get_analysis(db, user, analysis_id)
    result = analysis_service.stored_result(analysis)
    provider = build_provider(settings, request.app.state.http_client)
    if provider is not None and user.is_demo:
        # Anonymous visitors must not be able to spend the operator's model budget without bound.
        limiter: AttemptLimiter = request.app.state.external_limiter
        key = f"ai|{client_address(request)}"
        if limiter.blocked_for(key) > 0:
            provider = None
        else:
            limiter.record_failure(key)
    return explain(result, provider)


@router.get(
    "/analyses/{analysis_id}/forecast", response_model=ForecastResponse,
    summary="Unvalidated reference projections of the performance index",
    description="Persistence, moving average and robust linear trend. For orientation only: these projections are "
                "not validated, are not soiling forecasts and never enter a decision.",
)
def forecast(
    analysis_id: int, user: CurrentUser, db: DbSession,
    horizon_days: int = Query(default=14, ge=1, le=MAX_HORIZON_DAYS),
) -> ForecastResponse:
    analysis, _ = analysis_service.get_analysis(db, user, analysis_id)
    daily = analysis_service.stored_result(analysis).gap.daily
    # Only days with complete coverage: a partial day's index is not comparable.
    values = [d.performance_index * 100.0 if d.performance_index is not None and d.status == "OK" else None for d in daily]
    return ForecastResponse(
        analysis_id=analysis.id,
        forecast=forecast_performance_index([d.day for d in daily], values, horizon_days),
    )


_MEDIA = {
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
}


@router.get(
    "/analyses/{analysis_id}/report.{fmt}", summary="Export an analysis (HTML, PDF, CSV or JSON)",
    response_class=Response,
    responses={200: {"content": {m: {} for m in ("text/html", "application/pdf", "text/csv", "application/json")}}},
)
def report(analysis_id: int, fmt: Literal["html", "pdf", "csv", "json"], user: CurrentUser, db: DbSession,
           request: Request) -> Response:
    analysis, _ = analysis_service.get_analysis(db, user, analysis_id)
    result = analysis_service.stored_result(analysis)
    dataset = db.get(Dataset, analysis.dataset_id)
    author = db.get(User, analysis.created_by_id) if analysis.created_by_id is not None else None
    meta = ReportMeta(
        analysis_id=analysis.id,
        dataset_name=dataset.name if dataset is not None else None,
        dataset_sha256=dataset.content_sha256 if dataset is not None else None,
        created_at=analysis.created_at,
        created_by=(author.full_name or author.email) if author is not None else None,
    )
    body: str | bytes
    if fmt == "html":
        body = render_html(build_document(result, meta))
    elif fmt == "pdf":
        body = render_pdf(build_document(result, meta))
    elif fmt == "csv":
        body = render_csv(result, meta)
    else:
        body = render_json(result, meta)
    audit.record(db, "REPORT_EXPORTED", user=user, entity="analysis", entity_id=analysis.id, detail={"format": fmt},
                 remote_address=client_address(request))
    prefix = "SIMULATED-" if analysis.simulated else ""
    filename = f"solarwise-{prefix}analysis-{analysis.id}.{fmt}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"}
    if fmt == "html":
        # The report is a self-contained document: no scripts, no remote resources.
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    return Response(content=body, media_type=_MEDIA[fmt], headers=headers)
