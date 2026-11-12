"""External data: NASA POWER weather context and the PVGIS typical year."""

from __future__ import annotations

import hashlib
import json

import httpx
from fastapi import APIRouter, Request
from sqlalchemy import select

from solarwise.api.deps import AppSettings, CurrentUser, DbSession, client_address
from solarwise.api.errors import ApiError
from solarwise.api.routes.plants import _out as plant_out
from solarwise.api.schemas import DatasetOut, NasaPowerRequest, PlantOut, PvgisFetch, UploadCheck
from solarwise.db.models import Dataset, DatasetKind, PlantRole, User
from solarwise.ingestion.validator import validate_table
from solarwise.integrations import nasa_power, pvgis
from solarwise.integrations.base import IntegrationError, IntegrationFailure
from solarwise.security import AttemptLimiter
from solarwise.services import audit
from solarwise.services import datasets as dataset_service
from solarwise.services import plants as plant_service
from solarwise.services.errors import ConflictError, InvalidError

router = APIRouter(tags=["external data"])

_STATUS = {
    IntegrationFailure.DISABLED: 503,
    IntegrationFailure.UNAVAILABLE: 503,
    IntegrationFailure.REJECTED: 422,
    IntegrationFailure.UNEXPECTED_RESPONSE: 502,
}


def _failure(exc: IntegrationError) -> ApiError:
    """An external failure is reported as such.  No substitute data are ever produced."""
    return ApiError(
        _STATUS[exc.failure], f"EXTERNAL_{exc.failure.value}", str(exc),
        details={"service": exc.service, "failure": exc.failure.value, "data_returned": False},
    )


def _throttle_demo(request: Request, user: User) -> None:
    """Anonymous visitors may not use this server to send unbounded traffic to third parties."""
    if not user.is_demo:
        return
    limiter: AttemptLimiter = request.app.state.external_limiter
    key = f"ext|{client_address(request)}"
    wait = limiter.blocked_for(key)
    if wait > 0:
        raise ApiError(429, "TOO_MANY_REQUESTS", "too many external data requests from the demonstration; try again later",
                       headers={"Retry-After": str(int(wait) + 1)})
    limiter.record_failure(key)


@router.post(
    "/plants/{plant_id}/weather/nasa-power", response_model=UploadCheck,
    summary="Fetch daily weather context from NASA POWER",
    description="Modelled grid-cell values for the plant's coordinates, classified MODELLED. They pass through the "
                "same validation as an uploaded file. With `store=false` nothing is written.",
)
def nasa_power_import(plant_id: int, body: NasaPowerRequest, user: CurrentUser, db: DbSession, settings: AppSettings,
                      request: Request) -> UploadCheck:
    plant = plant_service.get_plant(db, user, plant_id, write=True)
    _throttle_demo(request, user)
    client: httpx.Client = request.app.state.http_client
    try:
        data = nasa_power.fetch_daily(
            client, settings.nasa_power_base_url, latitude=plant.latitude, longitude=plant.longitude,
            start=body.start, end=body.end, enabled=settings.external_data_enabled,
        )
    except ValueError as exc:
        raise InvalidError(str(exc)) from exc
    except IntegrationError as exc:
        raise _failure(exc) from exc
    table, metadata = nasa_power.to_upload(data, timezone=plant.timezone)
    report, parsed = validate_table(table, metadata, plant=plant_service.spec_of(plant))
    digest = hashlib.sha256(
        json.dumps({"rows": table.rows, "metadata": metadata.model_dump(mode="json")}, sort_keys=True, default=str).encode()
    ).hexdigest()
    duplicate = db.scalar(select(Dataset.id).where(Dataset.plant_id == plant.id, Dataset.content_sha256 == digest))
    dataset: Dataset | None = None
    if body.store:
        if duplicate is not None:
            raise ConflictError("these NASA POWER data have already been imported for this plant",
                                code="DUPLICATE_DATASET", details={"dataset_id": duplicate})
        if parsed is None or not report.accepted:
            raise InvalidError(report.summary, code="VALIDATION_FAILED", details=report.model_dump(mode="json"))
        dataset = dataset_service.store_parsed(
            db, plant, user, parsed=parsed, report=report, content_sha256=digest,
            file_name=None, kind=DatasetKind.WEATHER,
        )
        audit.record(db, "NASA_POWER_IMPORTED", user=user, entity="dataset", entity_id=dataset.id,
                     detail={"start": body.start.isoformat(), "end": body.end.isoformat()},
                     remote_address=client_address(request))
    return UploadCheck(
        accepted=report.accepted, stored=dataset is not None, duplicate_of=duplicate, content_sha256=digest,
        declared_metadata=metadata, report=report, dataset=DatasetOut.of(dataset) if dataset is not None else None,
    )


@router.post(
    "/plants/{plant_id}/pvgis/fetch", response_model=PlantOut,
    summary="Fetch the PVGIS typical-year monthly averages for the plant",
    description="Stores the twelve monthly averages on the plant, with their source. They describe a typical year, "
                "not the weather of the analysed period.",
)
def pvgis_fetch(plant_id: int, body: PvgisFetch, user: CurrentUser, db: DbSession, settings: AppSettings,
                request: Request) -> PlantOut:
    plant = plant_service.get_plant(db, user, plant_id, write=True)
    _throttle_demo(request, user)
    client: httpx.Client = request.app.state.http_client
    try:
        typical = pvgis.fetch_typical_year(
            client, settings.pvgis_base_url, plant_service.spec_of(plant), loss_pct=body.loss_pct,
            enabled=settings.external_data_enabled,
        )
    except ValueError as exc:
        raise InvalidError(str(exc), code="PLANT_DESCRIPTION_INCOMPLETE") from exc
    except IntegrationError as exc:
        raise _failure(exc) from exc
    plant_service.set_pvgis(db, plant, typical.months, typical.source)
    audit.record(db, "PVGIS_FETCHED", user=user, entity="plant", entity_id=plant.id,
                 detail={"source": typical.source[:200]}, remote_address=client_address(request))
    db.flush()
    return plant_out(db, user, plant, plant_service.plant_role(db, user, plant) or PlantRole.VIEWER.value)

