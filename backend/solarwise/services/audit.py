"""Audit trail of state-changing actions."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from solarwise.db.models import AuditLog, User


def record(
    db: Session,
    action: str,
    *,
    user: User | None = None,
    entity: str = "",
    entity_id: int | None = None,
    detail: dict[str, Any] | None = None,
    remote_address: str | None = None,
) -> None:
    db.add(
        AuditLog(
            action=action,
            user_id=user.id if user is not None else None,
            entity=entity,
            entity_id=entity_id,
            detail=detail,
            remote_address=remote_address,
        )
    )
