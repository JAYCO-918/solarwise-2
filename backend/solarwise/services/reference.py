"""Economic reference entries: documented sources, never applied automatically."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from solarwise.db.models import EconomicReference

CLASSIFICATIONS = ("OFFICIAL_REFERENCE", "MARKET_ESTIMATE", "USER_ASSUMPTION", "DEMONSTRATION_VALUE")
VERIFICATION_STATES = ("VERIFIED", "PENDING_VERIFICATION", "NOT_APPLICABLE")
_FIELDS = (
    "label", "category", "classification", "amount", "currency", "unit", "source_title", "source_reference",
    "verification_status", "applicability", "notes",
)


def load_document() -> dict[str, Any]:
    text = resources.files("solarwise.reference").joinpath("economic_references.json").read_text(encoding="utf-8")
    document: dict[str, Any] = json.loads(text)
    for entry in document["entries"]:
        if entry["classification"] not in CLASSIFICATIONS:
            raise ValueError(f"reference '{entry['key']}': unknown classification {entry['classification']!r}")
        if entry["verification_status"] not in VERIFICATION_STATES:
            raise ValueError(f"reference '{entry['key']}': unknown verification status")
        if (
            entry["classification"] == "OFFICIAL_REFERENCE"
            and entry["verification_status"] != "VERIFIED"
            and entry["amount"] is not None
        ):
            # An official figure that nobody has checked against its source must not circulate.
            raise ValueError(f"reference '{entry['key']}': an unverified official reference must not carry an amount")
    return document


def sync_reference_values(db: Session) -> int:
    """Insert or refresh the shipped entries (matched by key).  Returns the number of entries."""
    document = load_document()
    existing = {row.key: row for row in db.scalars(select(EconomicReference))}
    for entry in document["entries"]:
        row = existing.get(entry["key"])
        if row is None:
            row = EconomicReference(key=entry["key"])
            db.add(row)
        for name in _FIELDS:
            setattr(row, name, entry[name])
    return len(document["entries"])


def list_references(db: Session) -> list[EconomicReference]:
    return list(db.scalars(select(EconomicReference).order_by(EconomicReference.classification.desc(), EconomicReference.category, EconomicReference.key)))


def statement() -> str:
    return str(load_document()["statement"])
