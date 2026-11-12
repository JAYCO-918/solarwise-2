"""Documented evidence records."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import ValidationError

from solarwise.api.deps import CurrentUser, DbSession, client_address
from solarwise.api.schemas import EvidenceIn, EvidenceOut
from solarwise.core.models import EvidenceRecord
from solarwise.core.provenance import Provenance, ProvenanceTag
from solarwise.services import audit
from solarwise.services import evidence as evidence_service
from solarwise.services import plants as plant_service
from solarwise.services.errors import ConflictError, InvalidError

router = APIRouter(tags=["evidence"])


@router.get("/plants/{plant_id}/evidence", response_model=list[EvidenceOut], summary="Evidence records of a plant")
def list_evidence(plant_id: int, user: CurrentUser, db: DbSession) -> list[EvidenceOut]:
    plant = plant_service.get_plant(db, user, plant_id)
    return [EvidenceOut.of(row) for row in evidence_service.list_evidence(db, plant, everything=True)]


@router.post("/plants/{plant_id}/evidence", response_model=EvidenceOut, status_code=201, summary="Record evidence")
def add_evidence(plant_id: int, body: EvidenceIn, user: CurrentUser, db: DbSession, request: Request) -> EvidenceOut:
    plant = plant_service.get_plant(db, user, plant_id, write=True)
    provenance = body.provenance
    emulates = None
    if user.is_demo and provenance is not Provenance.SYNTHETIC:
        # Nothing entered in a demonstration session is a real observation of a real plant.
        emulates = provenance if provenance in (Provenance.MEASURED, Provenance.MODELLED) else None
        provenance = Provenance.SYNTHETIC
    try:
        tag = ProvenanceTag(
            provenance=provenance, emulates=emulates,
            source=body.source or ("origin not declared" if provenance is Provenance.UNKNOWN else ""),
            method=body.method,
        )
        record = EvidenceRecord(
            reference=body.reference.strip(), evidence_type=body.evidence_type, observed_start=body.observed_start,
            observed_end=body.observed_end, tag=tag, description=body.description, value=body.value, unit=body.unit,
            std_uncertainty=body.std_uncertainty, soiling_method=body.soiling_method, finding=body.finding,
            device_code=body.device_code, resolved=body.resolved, document_ref=body.document_ref,
        )
    except ValidationError as exc:
        raise InvalidError(
            "the evidence record is not valid",
            details=[{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()],
        ) from exc
    row = evidence_service.add_evidence(db, plant, user, record)
    audit.record(db, "EVIDENCE_ADDED", user=user, entity="evidence", entity_id=row.id,
                 detail={"type": record.evidence_type.value, "provenance": tag.label},
                 remote_address=client_address(request))
    return EvidenceOut.of(row)


@router.delete("/plants/{plant_id}/evidence/{evidence_id}", status_code=204, summary="Delete an evidence record")
def delete_evidence(plant_id: int, evidence_id: int, user: CurrentUser, db: DbSession, request: Request) -> Response:
    plant = plant_service.get_plant(db, user, plant_id, write=True)
    row = evidence_service.get_evidence(db, plant, evidence_id)
    if row.dataset_id is not None:
        raise ConflictError("evidence shipped with a demonstration scenario cannot be deleted")
    audit.record(db, "EVIDENCE_DELETED", user=user, entity="evidence", entity_id=row.id,
                 detail={"reference": row.reference}, remote_address=client_address(request))
    db.delete(row)
    return Response(status_code=204)
