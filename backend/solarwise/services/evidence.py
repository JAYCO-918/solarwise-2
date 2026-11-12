"""Documented evidence: soiling tests, inspections, faults, curtailment orders."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from solarwise.core.models import EvidenceRecord
from solarwise.db.models import Dataset, EvidenceRow, Plant, User
from solarwise.services.errors import ConflictError, NotFoundError


def add_evidence(
    db: Session, plant: Plant, user: User | None, record: EvidenceRecord, dataset: Dataset | None = None
) -> EvidenceRow:
    # References are unique among the plant's own records and within each dataset's attached records.
    scope = EvidenceRow.dataset_id.is_(None) if dataset is None else EvidenceRow.dataset_id == dataset.id
    exists = db.scalar(
        select(EvidenceRow.id).where(
            EvidenceRow.plant_id == plant.id, EvidenceRow.reference == record.reference, scope
        )
    )
    if exists is not None:
        raise ConflictError(f"evidence reference '{record.reference}' is already used for this plant",
                            code="EVIDENCE_REFERENCE_TAKEN")
    row = EvidenceRow(
        plant_id=plant.id,
        dataset_id=dataset.id if dataset is not None else None,
        reference=record.reference,
        evidence_type=record.evidence_type.value,
        observed_start=record.observed_start,
        observed_end=record.observed_end,
        record=record.model_dump(mode="json"),
        created_by_id=user.id if user is not None else None,
    )
    db.add(row)
    db.flush()
    return row


def list_evidence(db: Session, plant: Plant, dataset: Dataset | None = None, *, everything: bool = False) -> list[EvidenceRow]:
    """Evidence of the plant; records attached to a dataset apply to that dataset only."""
    query = select(EvidenceRow).where(EvidenceRow.plant_id == plant.id)
    if not everything:
        if dataset is None:
            query = query.where(EvidenceRow.dataset_id.is_(None))
        else:
            query = query.where(or_(EvidenceRow.dataset_id.is_(None), EvidenceRow.dataset_id == dataset.id))
    return list(db.scalars(query.order_by(EvidenceRow.observed_start.desc())))


def records_for(db: Session, plant: Plant, dataset: Dataset) -> list[EvidenceRecord]:
    return [EvidenceRecord.model_validate(row.record) for row in list_evidence(db, plant, dataset)]


def get_evidence(db: Session, plant: Plant, evidence_id: int) -> EvidenceRow:
    row = db.get(EvidenceRow, evidence_id)
    if row is None or row.plant_id != plant.id:
        raise NotFoundError("evidence record not found")
    return row
