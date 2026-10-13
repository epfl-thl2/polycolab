"""Human moderator-only public record hiding, with durable reasons and retries."""

from datetime import UTC
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor
from polycolab.access.authorization import (
    AuthorizationDenied,
    project_policy,
    require_human_actor,
)
from polycolab.catalogue.admission import is_moderator, lock_commons
from polycolab.db.models import (
    SqlCatalogueEntry,
    SqlProject,
    SqlPublicRelease,
    SqlRecordModeration,
    SqlRecordModerationAudit,
    SqlResearchObject,
    SqlResearchScope,
    SqlUser,
)
from polycolab.platform import mutation_keys
from polycolab.platform.config import Settings
from polycolab.platform.outbox import append_event
from polycolab.projects.service import DomainConflict
from polycolab.research.contracts import RecordModerationRead, RecordModerationWrite
from polycolab.research.objects import ResearchNotFound


def _audit_read(row: SqlRecordModerationAudit) -> RecordModerationRead:
    created_at = row.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return RecordModerationRead(
        id=row.id,
        object_id=row.object_id,
        object_version_id=row.revision_id,
        actor_user_id=row.actor_user_id,
        hidden=row.hidden,
        reason=row.reason,
        created_at=created_at,
    )


def history(
    session: Session, *, actor: Actor, object_id: UUID, limit: int, after: UUID | None
) -> list[RecordModerationRead]:
    require_human_actor(actor, action="moderation audit")
    assert actor.human_user_id is not None
    if not is_moderator(session, actor.human_user_id):
        raise AuthorizationDenied
    query = select(SqlRecordModerationAudit).where(SqlRecordModerationAudit.object_id == object_id)
    if after is not None:
        query = query.where(SqlRecordModerationAudit.id > after)
    return [
        _audit_read(row)
        for row in session.scalars(query.order_by(SqlRecordModerationAudit.id).limit(limit))
    ]


def moderate(
    session: Session, *, actor: Actor, object_id: UUID, payload: RecordModerationWrite, key: str
) -> RecordModerationRead:
    require_human_actor(actor, action="record moderation")
    user_id = actor.human_user_id
    assert user_id is not None
    body = {"object_id": str(object_id), **payload.model_dump(mode="json")}
    body["base_revision_id"] = body.pop("expected_current_object_version_id")
    actor_key = f"human:{user_id}"
    try:
        mutation_keys.lock_key(session, actor_key, "record.moderate", key)
        scope = lock_commons(session)
        if not is_moderator(session, user_id):
            raise AuthorizationDenied("record moderation requires an assigned moderator")
        obj = session.get(SqlResearchObject, object_id, populate_existing=True)
        if obj is None or obj.ownership_scope_id != scope.id:
            raise ResearchNotFound
        if session.get(SqlCatalogueEntry, obj.id) is not None:
            raise DomainConflict("use catalogue moderation for admitted statements")
        if (
            session.scalar(
                select(SqlPublicRelease.id).where(
                    SqlPublicRelease.object_revision_id
                    == payload.expected_current_object_version_id
                )
            )
            is None
        ):
            raise ResearchNotFound
        receipt = mutation_keys.receipt(session, actor_key, "record.moderate", key, body)
        if receipt is not None:
            audit = session.get(SqlRecordModerationAudit, UUID(receipt.resource_ids[0]))
            assert audit is not None
        else:
            if obj.current_revision_id != payload.expected_current_object_version_id:
                raise DomainConflict("stale moderation base")
            state = session.get(SqlRecordModeration, obj.id)
            if state is None:
                session.add(SqlRecordModeration(object_id=obj.id, hidden=payload.hidden))
            else:
                state.hidden = payload.hidden
            audit = SqlRecordModerationAudit(
                object_id=obj.id,
                revision_id=payload.expected_current_object_version_id,
                actor_user_id=user_id,
                hidden=payload.hidden,
                reason=payload.reason,
            )
            session.add(audit)
            session.flush()
            mutation_keys.save(session, actor_key, "record.moderate", key, body, [audit.id])
            append_event(
                session,
                event_type="record.moderated",
                aggregate_type="research_object",
                aggregate_id=obj.id,
                ownership_scope_id=scope.id,
                payload={
                    "revision_id": str(payload.expected_current_object_version_id),
                    "hidden": payload.hidden,
                },
            )
        result = _audit_read(audit)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise


def _public_project_operator(session: Session, *, actor: Actor, settings: Settings) -> SqlUser:
    """Resolve an explicitly configured human public-project moderation operator."""

    require_human_actor(actor, action="public project moderation")
    assert actor.human_user_id is not None
    user = session.get(SqlUser, actor.human_user_id)
    if user is None or user.subject not in settings.public_project_moderator_subjects:
        raise AuthorizationDenied
    return user


def moderate_public_project_record(
    session: Session,
    *,
    actor: Actor,
    settings: Settings,
    project_id: UUID,
    object_id: UUID,
    payload: RecordModerationWrite,
    key: str,
) -> RecordModerationRead:
    """Hide or restore one active public-project object with an immutable audit."""

    operator = _public_project_operator(session, actor=actor, settings=settings)
    body = {
        "project_id": str(project_id),
        "object_id": str(object_id),
        **payload.model_dump(mode="json"),
    }
    body["base_revision_id"] = body.pop("expected_current_object_version_id")
    actor_key = f"human:{operator.id}"
    operation = "project_record.moderate"
    try:
        mutation_keys.lock_key(session, actor_key, operation, key)
        project = session.scalar(
            select(SqlProject)
            .where(SqlProject.id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not project_policy.can_read_public(project):
            raise ResearchNotFound
        scope = session.scalar(
            select(SqlResearchScope).where(SqlResearchScope.project_id == project_id)
        )
        obj = session.scalar(
            select(SqlResearchObject)
            .where(
                SqlResearchObject.id == object_id,
                SqlResearchObject.ownership_scope_id == (scope.id if scope is not None else None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if obj is None:
            raise ResearchNotFound
        if obj.current_revision_id != payload.expected_current_object_version_id:
            raise DomainConflict("stale moderation base")
        receipt = mutation_keys.receipt(session, actor_key, operation, key, body)
        if receipt is not None:
            audit = session.get(SqlRecordModerationAudit, UUID(receipt.resource_ids[0]))
            if audit is None or audit.object_id != obj.id:
                raise ResearchNotFound
        else:
            state = session.get(SqlRecordModeration, obj.id)
            if state is None:
                session.add(SqlRecordModeration(object_id=obj.id, hidden=payload.hidden))
            else:
                state.hidden = payload.hidden
            audit = SqlRecordModerationAudit(
                object_id=obj.id,
                revision_id=payload.expected_current_object_version_id,
                actor_user_id=operator.id,
                hidden=payload.hidden,
                reason=payload.reason,
            )
            session.add(audit)
            session.flush()
            mutation_keys.save(session, actor_key, operation, key, body, [audit.id])
            append_event(
                session,
                event_type="project_record.moderated",
                aggregate_type="research_object",
                aggregate_id=obj.id,
                ownership_scope_id=scope.id if scope is not None else None,
                payload={
                    "schema_version": 1,
                    "revision_id": str(payload.expected_current_object_version_id),
                    "hidden": payload.hidden,
                },
            )
        result = _audit_read(audit)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise


def public_project_moderation_history(
    session: Session,
    *,
    actor: Actor,
    settings: Settings,
    project_id: UUID,
    object_id: UUID,
    limit: int,
    after: UUID | None,
) -> list[RecordModerationRead]:
    """Return an operator-only immutable audit without making it public research."""

    _public_project_operator(session, actor=actor, settings=settings)
    project = session.get(SqlProject, project_id)
    if project is None or project.deleted_at is not None:
        raise ResearchNotFound
    scope = session.scalar(
        select(SqlResearchScope).where(SqlResearchScope.project_id == project_id)
    )
    obj = session.get(SqlResearchObject, object_id)
    if scope is None or obj is None or obj.ownership_scope_id != scope.id:
        raise ResearchNotFound
    query = select(SqlRecordModerationAudit).where(SqlRecordModerationAudit.object_id == object_id)
    if after is not None:
        query = query.where(SqlRecordModerationAudit.id > after)
    return [
        _audit_read(row)
        for row in session.scalars(query.order_by(SqlRecordModerationAudit.id).limit(limit))
    ]
