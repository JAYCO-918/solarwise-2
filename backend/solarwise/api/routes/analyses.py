"""Analyses: run the engine on a stored dataset, read results, export reports."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Query, Request, Response

from solarwise.ai import (
    AiExplanation,
    Insight,
    build_operational_report,
    build_provider,
    deterministic_insight,
    explain,
    generate_insight,
    render_operational_json,
)
from solarwise.api.deps import AppSettings, CurrentUser, DbSession, client_address
from solarwise.api.language_model import provider_for
from solarwise.api.schemas import (
    AiStatus,
    AnalysisDetail,
    AnalysisRequest,
    AnalysisSummary,
    ForecastResponse,
    InsightOut,
    InsightRecord,
)
from solarwise.core.forecast import MAX_HORIZON_DAYS, forecast_performance_index
from solarwise.core.pipeline import AnalysisOptions
from solarwise.db.models import Analysis, Dataset, Role, User
from solarwise.reports import ReportMeta, build_document, render_csv, render_html, render_json, render_pdf
from solarwise.services import analysis as analysis_service
from solarwise.services import audit
from solarwise.services import datasets as dataset_service
from solarwise.services import insights as insight_service
from solarwise.services import plants as plant_service
from solarwise.services.errors import ForbiddenError, NotFoundError

router = APIRouter(tags=["analyses"])

AI_CAPABILITIES = [
    "diagnostic analysis of the engine's findings",
    "operational report",
    "explanation of the engine's decision",
    "review of the columns of an uploaded file",
    "plain-language rewording of the engine's explanation",
]


@router.get(
    "/ai/status", response_model=AiStatus, tags=["language model"],
    summary="Whether a language model is configured, and which",
    description="Never contains the key. Without a model every feature below still answers, with the engine's own text.",
)
def ai_status(settings: AppSettings, _: CurrentUser) -> AiStatus:
    enabled = build_provider(settings) is not None
    host = urlsplit(settings.ai_base_url).hostname if settings.ai_base_url else None
    return AiStatus(
        enabled=enabled,
        provider=settings.ai_provider if enabled else None,
        model=settings.ai_model if enabled else None,
        endpoint_host=host if enabled else None,
        capabilities=AI_CAPABILITIES,
        fallback="When no model is configured, cannot be reached or gives an answer that fails a check, the "
                 "deterministic engine's own text is shown instead, and the page says so.",
        role="A language model interprets and explains what the engine found. It never decides, never supplies a "
             "figure and never acts: the deterministic engine is the only authority for a recommendation.",
    )


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
    return explain(result, provider_for(request, settings, user))


def _insight_out(db: DbSession, analysis: Analysis) -> InsightOut:
    """The latest stored insight of the analysis; without one, the engine's own, assembled now and not stored."""
    row = insight_service.latest(db, analysis)
    if row is None:
        return InsightOut(stored=False, id=None, insight=deterministic_insight(analysis_service.stored_result(analysis)),
                          history=[])
    return InsightOut(
        stored=True, id=row.id, insight=insight_service.as_insight(row),
        history=[InsightRecord.of(r) for r in insight_service.history(db, analysis)],
    )


@router.get(
    "/analyses/{analysis_id}/insight", response_model=InsightOut, tags=["language model"],
    summary="The diagnostic analysis of an analysis",
    description="The interpretation last generated for the analysis, with what wrote it and when. When none was "
                "generated yet, the deterministic engine's own is returned (`stored: false`): no model is called by "
                "a read.",
)
def get_insight(analysis_id: int, user: CurrentUser, db: DbSession) -> InsightOut:
    analysis, _ = analysis_service.get_analysis(db, user, analysis_id)
    return _insight_out(db, analysis)


@router.post(
    "/analyses/{analysis_id}/insight", response_model=InsightOut, status_code=201, tags=["language model"],
    summary="Generate the diagnostic analysis",
    description="Asks the configured language model to interpret the engine's findings: what they mean, how the "
                "evidence weighs for and against each possible cause, what is uncertain or missing, and what matters "
                "most among the steps the engine proposed. The decision, the gates, the support levels, the evidence "
                "and the figures are copied from the engine by the server; the model writes the narrative only, and "
                "its text is checked against the findings. Without a model, or when a check fails, the engine's own "
                "text is used. Whatever was produced is stored with its origin.",
)
def create_insight(analysis_id: int, user: CurrentUser, db: DbSession, settings: AppSettings, request: Request) -> InsightOut:
    analysis, _ = analysis_service.get_analysis(db, user, analysis_id)
    if user.role == Role.VIEWER.value:
        raise ForbiddenError("your account is read-only")
    insight = generate_insight(analysis_service.stored_result(analysis), provider_for(request, settings, user))
    row = insight_service.store(db, analysis, user, insight)
    audit.record(db, "AI_INSIGHT_GENERATED", user=user, entity="analysis", entity_id=analysis.id,
                 detail={"insight_id": row.id, "generated_by": insight.generated_by, "provider": insight.provider,
                         "model": insight.model, "fell_back": insight.fallback_reason is not None,
                         "duration_ms": insight.duration_ms},
                 remote_address=client_address(request))
    return _insight_out(db, analysis)


def _stored_or_engine(db: DbSession, analysis: Analysis) -> Insight:
    row = insight_service.latest(db, analysis)
    if row is not None:
        return insight_service.as_insight(row)
    return deterministic_insight(analysis_service.stored_result(analysis))


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


def _report_meta(db: DbSession, analysis: Analysis) -> ReportMeta:
    dataset = db.get(Dataset, analysis.dataset_id)
    author = db.get(User, analysis.created_by_id) if analysis.created_by_id is not None else None
    return ReportMeta(
        analysis_id=analysis.id,
        dataset_name=dataset.name if dataset is not None else None,
        dataset_sha256=dataset.content_sha256 if dataset is not None else None,
        created_at=analysis.created_at,
        created_by=(author.full_name or author.email) if author is not None else None,
    )


@router.get(
    "/analyses/{analysis_id}/operational-report.{fmt}", tags=["language model"],
    summary="Export the operational report (HTML, PDF or JSON)",
    description="The diagnostic analysis as a document of eight sections: executive summary, performance, anomalies, "
                "diagnostic analysis, data quality, economic implications, recommended actions, limitations. Each "
                "section says whether a language model or the engine wrote it; the decision, the gates and the annex "
                "tables are always the engine's. Built from the insight last generated - or from the engine's own "
                "when none was. No model is called by an export.",
    response_class=Response,
    responses={200: {"content": {m: {} for m in ("text/html", "application/pdf", "application/json")}}},
)
def operational_report(analysis_id: int, fmt: Literal["html", "pdf", "json"], user: CurrentUser, db: DbSession,
                       request: Request) -> Response:
    analysis, _ = analysis_service.get_analysis(db, user, analysis_id)
    result = analysis_service.stored_result(analysis)
    insight = _stored_or_engine(db, analysis)
    meta = _report_meta(db, analysis)
    body: str | bytes
    if fmt == "json":
        body = render_operational_json(result, insight, meta)
    else:
        document = build_operational_report(result, insight, meta)
        body = render_html(document) if fmt == "html" else render_pdf(document)
    audit.record(db, "OPERATIONAL_REPORT_EXPORTED", user=user, entity="analysis", entity_id=analysis.id,
                 detail={"format": fmt, "narrative": insight.generated_by}, remote_address=client_address(request))
    prefix = "SIMULATED-" if analysis.simulated else ""
    filename = f"solarwise-{prefix}operational-report-{analysis.id}.{fmt}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"}
    if fmt == "html":
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    return Response(content=body, media_type=_MEDIA[fmt], headers=headers)


@router.get(
    "/analyses/{analysis_id}/report.{fmt}", summary="Export an analysis (HTML, PDF, CSV or JSON)",
    response_class=Response,
    responses={200: {"content": {m: {} for m in ("text/html", "application/pdf", "text/csv", "application/json")}}},
)
def report(analysis_id: int, fmt: Literal["html", "pdf", "csv", "json"], user: CurrentUser, db: DbSession,
           request: Request) -> Response:
    analysis, _ = analysis_service.get_analysis(db, user, analysis_id)
    result = analysis_service.stored_result(analysis)
    meta = _report_meta(db, analysis)
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
