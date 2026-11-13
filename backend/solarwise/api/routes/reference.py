"""Reference material: service information, data dictionary, decision rules, economic references."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from solarwise import __version__
from solarwise.api.deps import AppSettings, CurrentUser, DbSession
from solarwise.api.errors import ApiError
from solarwise.api.schemas import ReferenceOut
from solarwise.core import rules
from solarwise.core.economics import EnergyValueBasis, ValueClassification
from solarwise.core.models import (
    DIRECT_SOILING_METHODS,
    METRIC_SPECS,
    AnalysisThresholds,
    BaselineMethod,
    EvidenceType,
    InspectionFinding,
    IrradiancePlane,
    MeteringBoundary,
    SoilingMethod,
    TrackingType,
)
from solarwise.core.pipeline import ENGINE_VERSION
from solarwise.core.provenance import Provenance
from solarwise.core.units import accepted_units
from solarwise.demo.generator import SYNTHETIC_STATEMENT
from solarwise.ingestion import templates
from solarwise.ingestion.detect import accepted_units as units_of
from solarwise.ingestion.parser import MAX_COLUMNS, MAX_ROWS
from solarwise.ingestion.schema import DatasetMetadata
from solarwise.ingestion.validator import CLEANING_TOKENS, EVENT_VOCABULARY, MAX_EVENTS, NO_EVENT_TOKENS
from solarwise.services import datasets as dataset_service
from solarwise.services import reference as reference_service

router = APIRouter()

_PROVENANCE_MEANING = {
    Provenance.MEASURED: "Recorded by an instrument on the plant: revenue meter, inverter telemetry, pyranometer, "
                         "reference cell, soiling station.",
    Provenance.MODELLED: "Computed by a model or taken from satellite or reanalysis products (PVGIS, NASA POWER, a "
                         "performance simulation).",
    Provenance.SYNTHETIC: "Generated artificially for demonstration or testing. It may imitate a measurement but "
                          "describes no real plant.",
    Provenance.UNKNOWN: "Origin not declared. Treated as the weakest class.",
}


@router.get("/health", tags=["service"], summary="Liveness and database check")
def health(db: DbSession) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@router.get("/meta", tags=["service"], summary="What this server is and which optional features are on")
def meta(settings: AppSettings, request: Request) -> dict[str, Any]:
    return {
        "name": "SolarWise DZ",
        "version": __version__,
        "engine_version": ENGINE_VERSION,
        "demo_mode": settings.demo_mode,
        "registration_open": settings.allow_registration,
        "demo_statement": SYNTHETIC_STATEMENT if settings.demo_mode else None,
        "demo_limits": {
            "max_upload_mb": min(settings.max_upload_mb, dataset_service.DEMO_MAX_UPLOAD_MB),
            "max_datasets_per_plant": dataset_service.DEMO_MAX_DATASETS,
        },
        "max_upload_mb": settings.max_upload_mb,
        "external_data_enabled": settings.external_data_enabled,
        "ai": {
            "enabled": settings.ai_enabled,
            "provider": settings.ai_provider if settings.ai_provider != "none" else None,
            "role": "interprets and explains what the engine found; never decides, never supplies a figure",
        },
        "schema_revision": request.app.state.schema_state,
    }


@router.get("/reference/schema", tags=["reference"], summary="Data dictionary: columns, units, declarations")
def schema(_: CurrentUser) -> dict[str, Any]:
    return {
        "metrics": [
            {
                "metric": metric.value, "column": spec.column, "unit": spec.unit, "dimension": spec.dimension,
                "table": spec.table, "description": spec.description, "minimum": spec.minimum, "maximum": spec.maximum,
                # Irradiation columns also take irradiance (W/m2): the mean over each interval, converted with its length.
                "accepted_units": units_of(metric),
            }
            for metric, spec in METRIC_SPECS.items()
        ],
        "units": accepted_units(),
        "provenance": [{"value": p.value, "meaning": _PROVENANCE_MEANING[p]} for p in Provenance],
        "evidence_types": [e.value for e in EvidenceType],
        "inspection_findings": [f.value for f in InspectionFinding],
        "soiling_methods": [{"value": m.value, "direct": m in DIRECT_SOILING_METHODS} for m in SoilingMethod],
        "baseline_methods": [b.value for b in BaselineMethod],
        "metering_boundaries": [b.value for b in MeteringBoundary],
        "irradiance_planes": [p.value for p in IrradiancePlane],
        "tracking_types": [t.value for t in TrackingType],
        "energy_value_bases": [b.value for b in EnergyValueBasis],
        "value_classifications": [c.value for c in ValueClassification],
        "limits": {"max_rows": MAX_ROWS, "max_columns": MAX_COLUMNS},
        "missing_values": "An empty cell (or JSON null) means 'not observed'. It is never read as zero and never "
                          "interpolated.",
        "events": {
            "principle": "A cleaning mark or an alarm text found in a declared event column becomes an evidence "
                         "record of the dataset. Events never become numbers, and a logged fault is a reason to "
                         "investigate, never a reason to clean.",
            "cleaning_marks": sorted(CLEANING_TOKENS),
            "no_event_cells": sorted(t for t in NO_EVENT_TOKENS if t),
            "vocabulary": [{"evidence_type": kind.value, "matches": pattern.pattern} for kind, pattern in EVENT_VOCABULARY],
            "unmatched": "OTHER: shown with the analysis, not used by the diagnosis",
            "max_events_per_file": MAX_EVENTS,
        },
        "templates": [
            {"name": t.name, "title": t.title, "description": t.description, "example": t.example}
            for t in templates.TEMPLATES
        ],
        "metadata_schema": DatasetMetadata.model_json_schema(),
    }


@router.get(
    "/reference/templates/{name}", tags=["reference"], response_class=Response,
    summary="Download an upload template or example (CSV or JSON)",
    description="The templates hold column names and no data. The examples hold invented values for a hypothetical "
                "plant: they show the format and describe no real installation.",
    responses={200: {"content": {"text/csv": {}, "application/json": {}}}},
)
def template(name: str, _: CurrentUser) -> Response:
    found = templates.find(name)
    if found is None:
        raise ApiError(404, "NOT_FOUND", "no such template")
    return Response(
        content=templates.read(found), media_type=found.media_type,
        headers={"Content-Disposition": f'attachment; filename="{found.name}"', "Cache-Control": "no-store"},
    )


@router.get("/reference/decision-rules", tags=["reference"], summary="The decision rules, gates and thresholds")
def decision_rules(_: CurrentUser) -> dict[str, Any]:
    thresholds = AnalysisThresholds()
    return {
        "engine_version": ENGINE_VERSION,
        "principle": "A production gap is an observation, not a diagnosis. CLEAN_NOW requires every gate; anything "
                     "less is INVESTIGATE or MONITOR.",
        "gates": [g.model_dump(mode="json") for g in rules.GATES],
        "rules": [r.model_dump(mode="json") for r in rules.RULES],
        "thresholds": [
            {"name": name, "default": getattr(thresholds, name), "description": rules.THRESHOLD_DOCS.get(name, "")}
            for name in AnalysisThresholds.model_fields
        ],
    }


@router.get("/reference/economic", tags=["reference"], summary="Documented economic references")
def economic_references(_: CurrentUser, db: DbSession) -> dict[str, Any]:
    return {
        "statement": reference_service.statement(),
        "entries": [ReferenceOut.of(r).model_dump(mode="json") for r in reference_service.list_references(db)],
    }
