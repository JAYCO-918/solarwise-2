"""Datasets: validate, import, read."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from solarwise.api.deps import AppSettings, CurrentUser, DbSession, client_address
from solarwise.api.errors import ApiError
from solarwise.api.schemas import DatasetDetail, DatasetOut, UploadCheck
from solarwise.services import analysis as analysis_service
from solarwise.services import audit
from solarwise.services import datasets as dataset_service
from solarwise.services import plants as plant_service

router = APIRouter(tags=["datasets"])

_CHUNK = 1024 * 1024


async def _read(upload: UploadFile, limit_mb: int) -> bytes:
    """Read the upload, refusing it as soon as it exceeds the limit."""
    limit = limit_mb * 1024 * 1024
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await upload.read(_CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise ApiError(413, "PAYLOAD_TOO_LARGE", f"the file exceeds the {limit_mb} MB limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _limit_mb(settings: AppSettings, user: CurrentUser) -> int:
    return min(settings.max_upload_mb, dataset_service.DEMO_MAX_UPLOAD_MB) if user.is_demo else settings.max_upload_mb


def _check(db: DbSession, plant_id: int, user: CurrentUser, data: bytes, upload: UploadFile, metadata: str | None,
           *, write: bool) -> tuple[Any, dataset_service.Checked]:
    plant = plant_service.get_plant(db, user, plant_id, write=write)
    checked = dataset_service.check_upload(
        db, plant, data=data, filename=upload.filename, content_type=upload.content_type, metadata_json=metadata
    )
    return plant, checked


@router.get("/plants/{plant_id}/datasets", response_model=list[DatasetOut], summary="Datasets of a plant")
def list_datasets(plant_id: int, user: CurrentUser, db: DbSession, include_archived: bool = False) -> list[DatasetOut]:
    plant = plant_service.get_plant(db, user, plant_id)
    latest = analysis_service.latest_by_dataset(db, user, plant)
    return [
        DatasetOut.of(d, latest.get(d.id))
        for d in dataset_service.list_datasets(db, plant, include_archived=include_archived)
    ]


@router.post(
    "/plants/{plant_id}/datasets/validate", response_model=UploadCheck,
    summary="Validate a file without storing it",
    description="Step 1 of an import. Returns the complete validation report. Nothing is written.",
)
async def validate_upload(
    plant_id: int, user: CurrentUser, db: DbSession, settings: AppSettings,
    file: Annotated[UploadFile, File(description="CSV or JSON file")],
    metadata: Annotated[str | None, Form(description="Dataset metadata (JSON), see /reference/schema")] = None,
) -> UploadCheck:
    data = await _read(file, _limit_mb(settings, user))
    _, checked = _check(db, plant_id, user, data, file, metadata, write=False)
    return UploadCheck(
        accepted=checked.report.accepted, duplicate_of=checked.duplicate_of, content_sha256=checked.content_sha256,
        declared_metadata=checked.metadata, report=checked.report,
    )


@router.post(
    "/plants/{plant_id}/datasets", response_model=UploadCheck, status_code=201,
    summary="Import a file",
    description="Step 2 of an import: the file is validated again and stored if it is acceptable. "
                "Stored datasets are immutable.",
)
async def import_upload(
    plant_id: int, request: Request, user: CurrentUser, db: DbSession, settings: AppSettings,
    file: Annotated[UploadFile, File(description="CSV or JSON file")],
    metadata: Annotated[str | None, Form(description="Dataset metadata (JSON), see /reference/schema")] = None,
) -> UploadCheck:
    data = await _read(file, _limit_mb(settings, user))
    plant, checked = _check(db, plant_id, user, data, file, metadata, write=True)
    dataset = dataset_service.import_upload(db, plant, user, checked, file.filename)
    audit.record(db, "DATASET_IMPORTED", user=user, entity="dataset", entity_id=dataset.id,
                 detail={"sha256": checked.content_sha256, "rows": dataset.rows_plant + dataset.rows_device,
                         "synthetic": dataset.is_synthetic}, remote_address=client_address(request))
    return UploadCheck(
        accepted=True, stored=True, duplicate_of=None, content_sha256=checked.content_sha256,
        declared_metadata=checked.metadata, report=checked.report, dataset=DatasetOut.of(dataset),
    )


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail, summary="One dataset with its declarations")
def get_dataset(dataset_id: int, user: CurrentUser, db: DbSession) -> DatasetDetail:
    dataset, plant = dataset_service.get_dataset(db, user, dataset_id)
    return DatasetDetail.detail(dataset, analysis_service.latest_by_dataset(db, user, plant).get(dataset.id))


@router.get("/datasets/{dataset_id}/series", summary="Plant-level time series in canonical units")
def get_series(dataset_id: int, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    dataset, _ = dataset_service.get_dataset(db, user, dataset_id)
    return dataset_service.series_payload(db, dataset)


@router.delete("/datasets/{dataset_id}", status_code=204, summary="Archive a dataset",
               description="Datasets are never altered. Archiving hides a dataset; analyses made from it are kept.")
def archive_dataset(dataset_id: int, user: CurrentUser, db: DbSession, request: Request) -> Response:
    dataset, _ = dataset_service.get_dataset(db, user, dataset_id, write=True)
    if dataset.scenario_key is not None:
        raise ApiError(409, "CONFLICT", "demonstration scenarios cannot be archived")
    dataset.archived = True
    audit.record(db, "DATASET_ARCHIVED", user=user, entity="dataset", entity_id=dataset.id,
                 remote_address=client_address(request))
    return Response(status_code=204)
