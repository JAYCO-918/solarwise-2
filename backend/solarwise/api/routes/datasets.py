"""Datasets: preview, validate, import, read, export."""

from __future__ import annotations

import json
import re
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from solarwise.ai import DataReview, review_data
from solarwise.api.deps import AppSettings, CurrentUser, DbSession, client_address
from solarwise.api.errors import ApiError
from solarwise.api.language_model import provider_for
from solarwise.api.schemas import DatasetDetail, DatasetOut, OverlapOut, UploadCheck, UploadPreviewOut
from solarwise.db.models import Dataset, DatasetFile, User
from solarwise.services import analysis as analysis_service
from solarwise.services import audit
from solarwise.services import datasets as dataset_service
from solarwise.services import plants as plant_service

router = APIRouter(tags=["datasets"])

_CHUNK = 1024 * 1024
_UNSAFE_IN_FILE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


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
           *, write: bool, collect_rejections: bool = False) -> tuple[Any, dataset_service.Checked]:
    plant = plant_service.get_plant(db, user, plant_id, write=write)
    checked = dataset_service.check_upload(
        db, plant, data=data, filename=upload.filename, content_type=upload.content_type, metadata_json=metadata,
        collect_rejections=collect_rejections,
    )
    return plant, checked


def _upload_check(checked: dataset_service.Checked, **extra: Any) -> UploadCheck:
    return UploadCheck(
        accepted=checked.report.accepted, duplicate_of=checked.duplicate_of, content_sha256=checked.content_sha256,
        declared_metadata=checked.metadata, report=checked.report, file_sha256=checked.file_sha256,
        same_file_as=checked.same_file_as,
        overlapping=[OverlapOut(dataset_id=o.dataset_id, name=o.name, period_start=o.period_start, period_end=o.period_end)
                     for o in checked.overlapping],
        **extra,
    )


def _file_name(name: str | None, fallback: str) -> str:
    """A name that is safe inside a ``Content-Disposition`` header."""
    cleaned = _UNSAFE_IN_FILE_NAME.sub("_", (name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]).strip("._")
    return cleaned[:100] or fallback


def _attachment(content: bytes | str, media_type: str, file_name: str) -> Response:
    return Response(
        content=content, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{file_name}"', "Cache-Control": "no-store"},
    )


@router.get("/plants/{plant_id}/datasets", response_model=list[DatasetOut], summary="Datasets of a plant")
def list_datasets(plant_id: int, user: CurrentUser, db: DbSession, include_archived: bool = False) -> list[DatasetOut]:
    plant = plant_service.get_plant(db, user, plant_id)
    latest = analysis_service.latest_by_dataset(db, user, plant)
    return [
        DatasetOut.of(d, latest.get(d.id))
        for d in dataset_service.list_datasets(db, plant, include_archived=include_archived)
    ]


@router.post(
    "/plants/{plant_id}/datasets/preview", response_model=UploadPreviewOut,
    summary="Read a file and propose what its columns are",
    description="Step 1 of an import. Returns the first rows as they are in the file, what each column probably is "
                "(quantity and unit, read from the header), and what looks odd in the values. The proposal is "
                "deterministic and never includes a provenance. Nothing is validated, declared or written.",
)
async def preview_upload(
    plant_id: int, user: CurrentUser, db: DbSession, settings: AppSettings,
    file: Annotated[UploadFile, File(description="CSV or JSON file")],
) -> UploadPreviewOut:
    data = await _read(file, _limit_mb(settings, user))
    plant = plant_service.get_plant(db, user, plant_id)
    preview, file_sha256, same = dataset_service.preview_upload(
        db, plant, data=data, filename=file.filename, content_type=file.content_type
    )
    return UploadPreviewOut(
        file_name=file.filename or "", size_bytes=len(data), file_sha256=file_sha256, same_file_as=same, preview=preview
    )


@router.post(
    "/plants/{plant_id}/datasets/ai-review", response_model=DataReview, tags=["language model"],
    summary="Ask the language model to review the proposed mapping of a file",
    description="The model is given the column names, simple statistics and a few sample values - never the file - "
                "together with the deterministic proposal. It returns suggestions (another quantity or unit for a "
                "column), observations on the values, and context that is missing. Every suggestion is checked "
                "against the file and the accepted units; none is applied by the server, none names a provenance, "
                "and no value is ever changed. Without a model the answer says so and is empty.",
)
async def ai_review(
    plant_id: int, request: Request, user: CurrentUser, db: DbSession, settings: AppSettings,
    file: Annotated[UploadFile, File(description="CSV or JSON file")],
) -> DataReview:
    data = await _read(file, _limit_mb(settings, user))
    plant = plant_service.get_plant(db, user, plant_id)
    preview, file_sha256, _same = dataset_service.preview_upload(
        db, plant, data=data, filename=file.filename, content_type=file.content_type
    )
    # The provider may take as long as its time limit: the wait happens in a worker thread, not in the event loop,
    # so that the server goes on answering everybody else.
    review = await run_in_threadpool(
        review_data, preview, plant_service.spec_of(plant), provider_for(request, settings, user)
    )
    audit.record(db, "AI_DATA_REVIEW", user=user, entity="plant", entity_id=plant.id,
                 detail={"file_sha256": file_sha256, "generated_by": review.generated_by, "provider": review.provider,
                         "model": review.model, "suggestions": len(review.suggestions),
                         "discarded": len(review.discarded), "fell_back": review.fallback_reason is not None},
                 remote_address=client_address(request))
    return review


@router.post(
    "/plants/{plant_id}/datasets/validate", response_model=UploadCheck,
    summary="Validate a file without storing it",
    description="Step 2 of an import. Returns the complete validation report. Nothing is written.",
)
async def validate_upload(
    plant_id: int, user: CurrentUser, db: DbSession, settings: AppSettings,
    file: Annotated[UploadFile, File(description="CSV or JSON file")],
    metadata: Annotated[str | None, Form(description="Dataset metadata (JSON), see /reference/schema")] = None,
) -> UploadCheck:
    data = await _read(file, _limit_mb(settings, user))
    _, checked = _check(db, plant_id, user, data, file, metadata, write=False)
    return _upload_check(checked)


@router.post(
    "/plants/{plant_id}/datasets/rejected-rows", response_class=Response,
    summary="The rows of a file that would be rejected, with the reasons (CSV)",
    description="The rows that have a rejected cell, exactly as they are in the file, with the row number quoted in "
                "the validation report and the reason next to each. Nothing is written.",
    responses={200: {"content": {"text/csv": {}}}},
)
async def rejected_rows(
    plant_id: int, user: CurrentUser, db: DbSession, settings: AppSettings,
    file: Annotated[UploadFile, File(description="CSV or JSON file")],
    metadata: Annotated[str | None, Form(description="Dataset metadata (JSON), see /reference/schema")] = None,
) -> Response:
    data = await _read(file, _limit_mb(settings, user))
    _, checked = _check(db, plant_id, user, data, file, metadata, write=False, collect_rejections=True)
    body = dataset_service.rejected_rows_csv(checked.table, checked.rejections, checked.report.rejections_total)
    stem = _file_name(file.filename, "upload").rsplit(".", 1)[0]
    return _attachment(body, "text/csv; charset=utf-8", f"rejected-rows-{stem}.csv")


@router.post(
    "/plants/{plant_id}/datasets", response_model=UploadCheck, status_code=201,
    summary="Import a file",
    description="Step 3 of an import: the file is validated again and stored if it is acceptable - the values, the "
                "declarations, the file itself byte for byte, and the events it carries as evidence records. "
                "Stored datasets are immutable.",
)
async def import_upload(
    plant_id: int, request: Request, user: CurrentUser, db: DbSession, settings: AppSettings,
    file: Annotated[UploadFile, File(description="CSV or JSON file")],
    metadata: Annotated[str | None, Form(description="Dataset metadata (JSON), see /reference/schema")] = None,
) -> UploadCheck:
    data = await _read(file, _limit_mb(settings, user))
    plant, checked = _check(db, plant_id, user, data, file, metadata, write=True, collect_rejections=True)
    dataset = dataset_service.import_upload(db, plant, user, checked, file.filename)
    events = len(checked.parsed.events) if checked.parsed is not None else 0
    audit.record(db, "DATASET_IMPORTED", user=user, entity="dataset", entity_id=dataset.id,
                 detail={"sha256": checked.content_sha256, "file_sha256": checked.file_sha256,
                         "rows": dataset.rows_plant + dataset.rows_device, "synthetic": dataset.is_synthetic,
                         "events": events, "rejections": len(checked.rejections)},
                 remote_address=client_address(request))
    return _upload_check(checked, stored=True, dataset=DatasetOut.of(dataset), events_stored=events).model_copy(
        update={"accepted": True, "duplicate_of": None}
    )


def _detail(db: DbSession, user: User, dataset: Dataset, plant: Any) -> DatasetDetail:
    return DatasetDetail.detail(
        dataset, analysis_service.latest_by_dataset(db, user, plant).get(dataset.id),
        original=db.get(DatasetFile, dataset.id), events=dataset_service.events_of(db, dataset),
    )


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail, summary="One dataset with its declarations")
def get_dataset(dataset_id: int, user: CurrentUser, db: DbSession) -> DatasetDetail:
    dataset, plant = dataset_service.get_dataset(db, user, dataset_id)
    return _detail(db, user, dataset, plant)


@router.get("/datasets/{dataset_id}/series", summary="Plant-level time series in canonical units")
def get_series(dataset_id: int, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    dataset, _ = dataset_service.get_dataset(db, user, dataset_id)
    return dataset_service.series_payload(db, dataset)


@router.get(
    "/datasets/{dataset_id}/file", response_class=Response,
    summary="The file the dataset was imported from, byte for byte",
    description="Always sent as an attachment. 404 `NO_ORIGINAL_FILE` for a dataset that did not come from an upload "
                "(demonstration scenario, NASA POWER) or that was imported before files were kept.",
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def get_original_file(dataset_id: int, user: CurrentUser, db: DbSession, request: Request) -> Response:
    dataset, _ = dataset_service.get_dataset(db, user, dataset_id)
    original = dataset_service.original_file(db, dataset)
    if original is None:
        raise ApiError(404, "NO_ORIGINAL_FILE", "no uploaded file is kept for this dataset")
    stored, data = original
    audit.record(db, "ORIGINAL_FILE_EXPORTED", user=user, entity="dataset", entity_id=dataset.id,
                 detail={"sha256": stored.sha256}, remote_address=client_address(request))
    extension = "json" if dataset.file_format == "JSON" else "csv"
    # Never a type a browser would render: the content is whatever was uploaded.
    return _attachment(data, "application/octet-stream", _file_name(stored.file_name, f"dataset-{dataset.id}.{extension}"))


@router.get(
    "/datasets/{dataset_id}/rejected-rows.csv", response_class=Response,
    summary="The rows rejected when the dataset was imported, with the reasons (CSV)",
    description="As recorded at import. A dataset in which nothing was rejected returns the header line only.",
    responses={200: {"content": {"text/csv": {}}}},
)
def get_rejected_rows(dataset_id: int, user: CurrentUser, db: DbSession) -> Response:
    dataset, _ = dataset_service.get_dataset(db, user, dataset_id)
    if db.get(DatasetFile, dataset.id) is None:
        raise ApiError(404, "NO_ORIGINAL_FILE", "no uploaded file is kept for this dataset")
    body = dataset_service.stored_rejected_rows(db, dataset)
    if body is None:
        body = "solarwise_row,solarwise_problems\n"
    return _attachment(body, "text/csv; charset=utf-8", f"rejected-rows-dataset-{dataset.id}.csv")


@router.get(
    "/datasets/{dataset_id}/validation-report.json", response_class=Response,
    summary="The validation report and the declarations of a dataset (JSON)",
    responses={200: {"content": {"application/json": {}}}},
)
def get_validation_report(dataset_id: int, user: CurrentUser, db: DbSession) -> Response:
    dataset, _ = dataset_service.get_dataset(db, user, dataset_id)
    stored = db.get(DatasetFile, dataset.id)
    author = db.get(User, dataset.created_by_id) if dataset.created_by_id is not None else None
    document = {
        "report": {"format": "solarwise-validation", "format_version": 1},
        "dataset": {
            "id": dataset.id, "name": dataset.name, "plant_id": dataset.plant_id, "file_name": dataset.file_name,
            "file_format": dataset.file_format, "imported_at": dataset.created_at.isoformat(),
            "imported_by": (author.full_name or author.email) if author is not None else None,
            "content_sha256": dataset.content_sha256, "file_sha256": stored.sha256 if stored is not None else None,
            "is_synthetic": dataset.is_synthetic,
        },
        "declared_metadata": dataset.declared_metadata,
        "validation_report": dataset.validation_report,
    }
    return _attachment(json.dumps(document, indent=2, ensure_ascii=False), "application/json",
                       f"validation-report-dataset-{dataset.id}.json")


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
