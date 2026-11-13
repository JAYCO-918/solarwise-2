"""Insights: interpretations of an analysis, kept as they were written.

An insight never touches the analysis it reads.  Every one that is generated is
stored with what produced it - the model and provider, or the note that none was
used - the time, the checks it passed and the fingerprint of the evidence it was
written from, so that a text shown to an operator can always be traced.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from solarwise.ai.analyst import Insight
from solarwise.db.models import AiInsight, Analysis, User

#: Insights kept per analysis; older ones are pruned.
KEPT_PER_ANALYSIS = 10


def latest(db: Session, analysis: Analysis) -> AiInsight | None:
    return db.scalar(
        select(AiInsight).where(AiInsight.analysis_id == analysis.id)
        .order_by(AiInsight.created_at.desc(), AiInsight.id.desc()).limit(1)
    )


def as_insight(row: AiInsight) -> Insight:
    return Insight.model_validate(row.content)


def store(db: Session, analysis: Analysis, user: User | None, insight: Insight) -> AiInsight:
    row = AiInsight(
        analysis_id=analysis.id,
        created_by_id=user.id if user is not None else None,
        created_at=insight.generated_at,
        generated_by=insight.generated_by,
        provider=insight.provider,
        model=insight.model,
        prompt_version=insight.prompt_version,
        packet_sha256=insight.packet_sha256,
        duration_ms=insight.duration_ms,
        fallback_reason=insight.fallback_reason,
        checks=[c.model_dump(mode="json") for c in insight.checks],
        content=insight.model_dump(mode="json"),
    )
    db.add(row)
    db.flush()
    stale = db.scalars(
        select(AiInsight).where(AiInsight.analysis_id == analysis.id)
        .order_by(AiInsight.created_at.desc(), AiInsight.id.desc()).offset(KEPT_PER_ANALYSIS)
    )
    for old in stale:
        db.delete(old)
    return row


def history(db: Session, analysis: Analysis) -> list[AiInsight]:
    return list(
        db.scalars(
            select(AiInsight).where(AiInsight.analysis_id == analysis.id)
            .order_by(AiInsight.created_at.desc(), AiInsight.id.desc())
        )
    )
