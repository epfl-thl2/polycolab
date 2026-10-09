"""Authorized bounded discovery of curated verification environments."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.db.models import SqlVerificationEnvironment
from polycolab.entities.enums import VerificationLanguage
from polycolab.research.records import project_access


def available(
    session: Session,
    *,
    project_id: UUID,
    user_id: UUID,
    after: UUID | None,
    limit: int,
    language: VerificationLanguage | None = None,
) -> tuple[list[SqlVerificationEnvironment], UUID | None]:
    """List stable environment identities after current project authorization."""

    if not 1 <= limit <= 100:
        raise ValueError("invalid verification environment page size")
    project_access(session, project_id, user_id)
    query = select(SqlVerificationEnvironment).where(SqlVerificationEnvironment.available.is_(True))
    if after is not None:
        query = query.where(SqlVerificationEnvironment.id > after)
    if language is not None:
        query = query.where(SqlVerificationEnvironment.language == language)
    rows = list(session.scalars(query.order_by(SqlVerificationEnvironment.id).limit(limit + 1)))
    next_after = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_after
