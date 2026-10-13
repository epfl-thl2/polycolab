"""Associated note, summary, comment, and reported-progress histories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor, ActorKind, ActorOperation
from polycolab.access.authorization import (
    AuthorizationDenied,
    ProjectAction,
    project_policy,
    require_human_actor,
)
from polycolab.catalogue.admission import is_moderator, lock_commons
from polycolab.db.models import (
    SqlContributionEnvelope,
    SqlExternalAgentCredential,
    SqlExternalAgentIdentity,
    SqlHumanNote,
    SqlHumanNoteRevision,
    SqlObjectRevision,
    SqlPlatformAgentVersion,
    SqlResearchComment,
    SqlResearchObject,
    SqlResearchProgressUpdate,
    SqlResearchSummary,
    SqlResearchSummaryRevision,
    SqlSummarySourceRevision,
    SqlUser,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import ProvenanceKind
from polycolab.platform import mutation_keys
from polycolab.projects.service import DomainConflict
from polycolab.research.contracts import (
    HumanNotePage,
    HumanNoteRead,
    HumanNoteRevisionRead,
    HumanNoteWrite,
    ResearchCommentPage,
    ResearchCommentRead,
    ResearchCommentWrite,
    ResearchProgressPage,
    ResearchProgressRead,
    ResearchProgressWrite,
    ResearchSummaryPage,
    ResearchSummaryRead,
    ResearchSummaryRevisionRead,
    ResearchSummaryWrite,
)
from polycolab.research.contributions import human_contribution
from polycolab.research.objects import ResearchNotFound
from polycolab.research.records import (
    accessible_revision,
    decode_cursor,
    encode_cursor,
    project_access,
    read_condition,
)


@dataclass(frozen=True, slots=True)
class _Target:
    object: SqlResearchObject
    revision: SqlObjectRevision
    user_id: UUID


def _actor_user_id(actor: Actor) -> UUID:
    value = actor.human_user_id if actor.kind is ActorKind.HUMAN else actor.sponsor_user_id
    if value is None:
        raise AuthorizationDenied
    return value


def _actor_key(actor: Actor) -> str:
    if actor.kind is ActorKind.HUMAN:
        return f"human:{_actor_user_id(actor)}"
    if actor.run_id is None and actor.external_run_id is None and actor.external_agent_id is None:
        raise AuthorizationDenied
    return f"agent:{actor.external_agent_id or actor.external_run_id or actor.run_id}"


def _target(
    session: Session,
    *,
    actor: Actor,
    object_id: UUID,
    revision_id: UUID | None,
    project_id: UUID | None,
    write: bool,
) -> _Target:
    user_id = _actor_user_id(actor)
    if project_id is not None:
        project_access(session, project_id, user_id, write=write)
    elif write:
        lock_commons(session)
    obj = session.get(SqlResearchObject, object_id)
    if obj is None or obj.project_id != project_id:
        raise ResearchNotFound
    selected = revision_id or obj.current_revision_id
    if selected is None:
        raise ResearchNotFound
    revision = accessible_revision(session, selected, project_id)
    if revision.object_id != obj.id:
        raise ResearchNotFound
    return _Target(obj, revision, user_id)


def _contribution(
    session: Session,
    *,
    actor: Actor,
    target: _Target,
    operation: str,
    required_operation: ActorOperation,
    contribution: SqlContributionEnvelope | None,
) -> SqlContributionEnvelope:
    if actor.kind is ActorKind.HUMAN and contribution is not None:
        if (
            contribution.human_user_id != actor.human_user_id
            or contribution.ownership_scope_id != target.object.ownership_scope_id
        ):
            raise AuthorizationDenied("contribution authority mismatch")
        return contribution
    if actor.kind is ActorKind.HUMAN:
        return human_contribution(
            session,
            user_id=target.user_id,
            scope_id=target.object.ownership_scope_id,
            operation=operation,
        )
    if (
        contribution is None
        or contribution.ownership_scope_id != target.object.ownership_scope_id
        or contribution.run_id != actor.run_id
        or required_operation not in actor.operation_scope
    ):
        raise AuthorizationDenied("missing validated contribution authority")
    return contribution


def _attribution(
    session: Session, contribution_id: UUID, created_by_user_id: UUID
) -> tuple[str | None, str, str | None]:
    user = session.get(SqlUser, created_by_user_id)
    envelope = session.get(SqlContributionEnvelope, contribution_id)
    if user is None or envelope is None:
        raise ResearchNotFound
    agent = (
        session.get(SqlPlatformAgentVersion, envelope.agent_version_id)
        if envelope.agent_version_id
        else None
    )
    agent_name = agent.display_name if agent else None
    identity_id = envelope.external_agent_id
    if identity_id is None and envelope.external_credential_id:
        credential = session.get(SqlExternalAgentCredential, envelope.external_credential_id)
        identity_id = credential.agent_id if credential else None
    if identity_id:
        identity = session.get(SqlExternalAgentIdentity, identity_id)
        agent_name = identity.name if identity else agent_name
    return user.display_name, envelope.actor_kind.value, agent_name


def _note_revision_read(session: Session, row: SqlHumanNoteRevision) -> HumanNoteRevisionRead:
    user = session.get(SqlUser, row.created_by_user_id)
    if user is None:
        raise ResearchNotFound
    return HumanNoteRevisionRead(
        id=row.id,
        object_id=row.object_id,
        number=row.number,
        base_revision_id=row.base_revision_id,
        body_md=row.body_md,
        author_display_name=user.display_name,
        created_at=row.created_at,
    )


def write_human_note(
    session: Session,
    *,
    actor: Actor,
    object_id: UUID,
    payload: HumanNoteWrite,
    key: str,
) -> HumanNoteRead:
    require_human_actor(actor, action="dedicated human note")
    target = _target(
        session,
        actor=actor,
        object_id=object_id,
        revision_id=None,
        project_id=payload.project_id,
        write=True,
    )
    actor_key = _actor_key(actor)
    body = {"object_id": str(object_id), **payload.model_dump(mode="json")}
    try:
        mutation_keys.lock_key(session, actor_key, "research.human_note", key)
        note = session.scalar(
            select(SqlHumanNote)
            .where(SqlHumanNote.object_id == object_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        existing = mutation_keys.receipt(session, actor_key, "research.human_note", key, body)
        if existing is not None:
            row = session.get(SqlHumanNoteRevision, UUID(existing.resource_ids[0]))
            if row is None:
                raise ResearchNotFound
            session.commit()
            note = session.get(SqlHumanNote, object_id)
            assert note is not None
            return _human_note_read(
                session,
                note,
                row,
                actor_user_id=target.user_id,
                project_id=payload.project_id,
            )
        if note is None:
            if payload.base_revision_id is not None:
                raise DomainConflict("new human note must not supply a base")
            note = SqlHumanNote(
                object_id=object_id,
                ownership_scope_id=target.object.ownership_scope_id,
                owner_user_id=target.user_id,
            )
            session.add(note)
            number = 1
        else:
            if note.owner_user_id != target.user_id:
                raise AuthorizationDenied("only the human-note owner may revise it")
            if note.current_revision_id != payload.base_revision_id:
                raise DomainConflict("stale human-note revision")
            current = session.get(SqlHumanNoteRevision, note.current_revision_id)
            if current is None:
                raise ResearchNotFound
            number = current.number + 1
        envelope = human_contribution(
            session,
            user_id=target.user_id,
            scope_id=target.object.ownership_scope_id,
            operation="research.human_note",
        )
        row = SqlHumanNoteRevision(
            object_id=object_id,
            number=number,
            base_revision_id=payload.base_revision_id,
            body_md=payload.body_md,
            contribution_id=envelope.id,
            created_by_user_id=target.user_id,
        )
        session.add(row)
        session.flush()
        note.current_revision_id = row.id
        mutation_keys.save(session, actor_key, "research.human_note", key, body, [row.id])
        session.commit()
        session.refresh(row)
        return _human_note_read(
            session,
            note,
            row,
            actor_user_id=target.user_id,
            project_id=payload.project_id,
        )
    except Exception:
        session.rollback()
        raise


def _human_note_read(
    session: Session,
    note: SqlHumanNote,
    revision: SqlHumanNoteRevision,
    *,
    actor_user_id: UUID,
    project_id: UUID | None,
) -> HumanNoteRead:
    owner = session.get(SqlUser, note.owner_user_id)
    if owner is None:
        raise ResearchNotFound
    return HumanNoteRead(
        object_id=note.object_id,
        owner_user_id=note.owner_user_id,
        owner_display_name=owner.display_name,
        can_edit=note.owner_user_id == actor_user_id
        and (
            project_id is None
            or project_policy.can(
                SqlAlchemyTransaction(session),
                project_id,
                actor_user_id,
                ProjectAction.CREATE_RESEARCH,
            )
        ),
        current_revision=_note_revision_read(session, revision),
    )


def get_human_note(
    session: Session, *, actor: Actor, object_id: UUID, project_id: UUID | None
) -> HumanNoteRead:
    _target(
        session,
        actor=actor,
        object_id=object_id,
        revision_id=None,
        project_id=project_id,
        write=False,
    )
    note = session.get(SqlHumanNote, object_id)
    if note is None or note.current_revision_id is None:
        raise ResearchNotFound
    if (
        project_id is None
        and note.owner_user_id != _actor_user_id(actor)
        and not is_moderator(session, _actor_user_id(actor))
    ):
        raise ResearchNotFound
    revision = session.get(SqlHumanNoteRevision, note.current_revision_id)
    if revision is None:
        raise ResearchNotFound
    return _human_note_read(
        session,
        note,
        revision,
        actor_user_id=_actor_user_id(actor),
        project_id=project_id,
    )


def human_note_history(
    session: Session,
    *,
    actor: Actor,
    object_id: UUID,
    project_id: UUID | None,
    limit: int,
    cursor: str | None,
) -> HumanNotePage:
    get_human_note(session, actor=actor, object_id=object_id, project_id=project_id)
    query = select(SqlHumanNoteRevision).where(SqlHumanNoteRevision.object_id == object_id)
    if cursor:
        anchor = session.get(SqlHumanNoteRevision, decode_cursor(cursor))
        if anchor is None or anchor.object_id != object_id:
            raise DomainConflict("invalid cursor")
        query = query.where(SqlHumanNoteRevision.number > anchor.number)
    rows = list(session.scalars(query.order_by(SqlHumanNoteRevision.number).limit(limit + 1)))
    return HumanNotePage(
        items=[_note_revision_read(session, row) for row in rows[:limit]],
        next_cursor=encode_cursor(rows[limit - 1].id) if len(rows) > limit else None,
    )


def _summary_revision_read(
    session: Session, row: SqlResearchSummaryRevision, project_id: UUID | None
) -> ResearchSummaryRevisionRead:
    author_name, actor_kind, agent_name = _attribution(
        session, row.contribution_id, row.created_by_user_id
    )
    sources = list(
        session.scalars(
            select(SqlSummarySourceRevision.source_revision_id)
            .where(SqlSummarySourceRevision.summary_revision_id == row.id)
            .order_by(SqlSummarySourceRevision.position)
        )
    )
    source_rows = list(
        session.execute(
            select(
                SqlObjectRevision.id, SqlObjectRevision.object_id, SqlObjectRevision.number
            ).where(SqlObjectRevision.id.in_(sources))
        )
    )
    object_ids = {object_id for _, object_id, _ in source_rows}
    visible_numbers: dict[UUID, int] = {
        object_id: number
        for object_id, number in session.execute(
            select(SqlObjectRevision.object_id, func.max(SqlObjectRevision.number))
            .where(
                SqlObjectRevision.object_id.in_(object_ids),
                read_condition(project_id),
            )
            .group_by(SqlObjectRevision.object_id)
        )
    }
    fresh = len(source_rows) == len(sources) and all(
        number == visible_numbers.get(object_id) for _, object_id, number in source_rows
    )
    return ResearchSummaryRevisionRead(
        id=row.id,
        object_id=row.object_id,
        number=row.number,
        base_revision_id=row.base_revision_id,
        body_md=row.body_md,
        source_revision_ids=sources,
        fresh=fresh,
        author_display_name=author_name,
        actor_kind=actor_kind,
        agent_display_name=agent_name,
        created_at=row.created_at.replace(tzinfo=UTC)
        if row.created_at.tzinfo is None
        else row.created_at.astimezone(UTC),
    )


def _summary_read(
    session: Session,
    summary: SqlResearchSummary,
    revision: SqlResearchSummaryRevision,
    project_id: UUID | None,
) -> ResearchSummaryRead:
    owner = session.get(SqlUser, summary.owner_user_id)
    if owner is None:
        raise ResearchNotFound
    return ResearchSummaryRead(
        object_id=summary.object_id,
        owner_display_name=owner.display_name,
        current_revision=_summary_revision_read(session, revision, project_id),
    )


def write_summary(
    session: Session,
    *,
    actor: Actor,
    object_id: UUID,
    payload: ResearchSummaryWrite,
    key: str,
    contribution: SqlContributionEnvelope | None = None,
    commit: bool = True,
) -> ResearchSummaryRead:
    target = _target(
        session,
        actor=actor,
        object_id=object_id,
        revision_id=None,
        project_id=payload.project_id,
        write=True,
    )
    actor_key = _actor_key(actor)
    body = {"object_id": str(object_id), **payload.model_dump(mode="json")}
    try:
        mutation_keys.lock_key(session, actor_key, "research.summary", key)
        summary = session.scalar(
            select(SqlResearchSummary)
            .where(SqlResearchSummary.object_id == object_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        existing = mutation_keys.receipt(session, actor_key, "research.summary", key, body)
        if existing is not None:
            row = session.get(SqlResearchSummaryRevision, UUID(existing.resource_ids[0]))
            if row is None:
                raise ResearchNotFound
            if commit:
                session.commit()
            summary = session.get(SqlResearchSummary, object_id)
            assert summary is not None
            return _summary_read(session, summary, row, payload.project_id)
        for revision_id in payload.source_revision_ids:
            accessible_revision(session, revision_id, payload.project_id)
        operation = (
            ActorOperation.CONTRIBUTION_CREATE
            if summary is None
            else ActorOperation.CONTRIBUTION_EDIT
        )
        envelope = _contribution(
            session,
            actor=actor,
            target=target,
            operation="research.summary",
            required_operation=operation,
            contribution=contribution,
        )
        if summary is None:
            if payload.base_revision_id is not None:
                raise DomainConflict("new summary must not supply a base")
            summary = SqlResearchSummary(
                object_id=object_id,
                ownership_scope_id=target.object.ownership_scope_id,
                owner_user_id=target.user_id,
            )
            session.add(summary)
            number = 1
        else:
            if summary.owner_user_id != target.user_id and not (
                payload.project_id is None
                and actor.kind is ActorKind.HUMAN
                and is_moderator(session, target.user_id)
            ):
                raise AuthorizationDenied("only the summary author or editor may revise it")
            if summary.current_revision_id != payload.base_revision_id:
                raise DomainConflict("stale summary revision")
            current = session.get(SqlResearchSummaryRevision, summary.current_revision_id)
            if current is None:
                raise ResearchNotFound
            number = current.number + 1
        row = SqlResearchSummaryRevision(
            object_id=object_id,
            number=number,
            base_revision_id=payload.base_revision_id,
            body_md=payload.body_md,
            contribution_id=envelope.id,
            created_by_user_id=target.user_id,
        )
        session.add(row)
        session.flush()
        for position, revision_id in enumerate(payload.source_revision_ids):
            session.add(
                SqlSummarySourceRevision(
                    summary_revision_id=row.id,
                    source_revision_id=revision_id,
                    position=position,
                )
            )
        summary.current_revision_id = row.id
        mutation_keys.save(session, actor_key, "research.summary", key, body, [row.id])
        if commit:
            session.commit()
            session.refresh(row)
        else:
            session.flush()
        return _summary_read(session, summary, row, payload.project_id)
    except Exception:
        session.rollback()
        raise


def get_summary(
    session: Session, *, actor: Actor, object_id: UUID, project_id: UUID | None
) -> ResearchSummaryRead:
    _target(
        session,
        actor=actor,
        object_id=object_id,
        revision_id=None,
        project_id=project_id,
        write=False,
    )
    summary = session.get(SqlResearchSummary, object_id)
    if summary is None or summary.current_revision_id is None:
        raise ResearchNotFound
    revision = session.get(SqlResearchSummaryRevision, summary.current_revision_id)
    if revision is None:
        raise ResearchNotFound
    for source_id in _summary_revision_read(session, revision, project_id).source_revision_ids:
        accessible_revision(session, source_id, project_id)
    return _summary_read(session, summary, revision, project_id)


def summary_history(
    session: Session,
    *,
    actor: Actor,
    object_id: UUID,
    project_id: UUID | None,
    limit: int,
    cursor: str | None,
) -> ResearchSummaryPage:
    get_summary(session, actor=actor, object_id=object_id, project_id=project_id)
    query = select(SqlResearchSummaryRevision).where(
        SqlResearchSummaryRevision.object_id == object_id
    )
    if cursor:
        anchor = session.get(SqlResearchSummaryRevision, decode_cursor(cursor))
        if anchor is None or anchor.object_id != object_id:
            raise DomainConflict("invalid cursor")
        query = query.where(SqlResearchSummaryRevision.number > anchor.number)
    rows = list(session.scalars(query.order_by(SqlResearchSummaryRevision.number).limit(limit + 1)))
    visible: list[ResearchSummaryRevisionRead] = []
    for row in rows:
        item = _summary_revision_read(session, row, project_id)
        for source_id in item.source_revision_ids:
            accessible_revision(session, source_id, project_id)
        visible.append(item)
    return ResearchSummaryPage(
        items=visible[:limit],
        next_cursor=encode_cursor(rows[limit - 1].id) if len(rows) > limit else None,
    )


def _progress_read(session: Session, row: SqlResearchProgressUpdate) -> ResearchProgressRead:
    author_name, actor_kind, agent_name = _attribution(
        session, row.contribution_id, row.created_by_user_id
    )
    return ResearchProgressRead(
        id=row.id,
        object_id=row.object_id,
        revision_id=row.revision_id,
        status=row.status,
        detail_md=row.detail_md,
        author_display_name=author_name,
        actor_kind=actor_kind,
        agent_display_name=agent_name,
        created_at=row.created_at.replace(tzinfo=UTC)
        if row.created_at.tzinfo is None
        else row.created_at.astimezone(UTC),
    )


def write_progress(
    session: Session,
    *,
    actor: Actor,
    object_id: UUID,
    payload: ResearchProgressWrite,
    key: str,
    contribution: SqlContributionEnvelope | None = None,
    commit: bool = True,
) -> ResearchProgressRead:
    target = _target(
        session,
        actor=actor,
        object_id=object_id,
        revision_id=payload.revision_id,
        project_id=payload.project_id,
        write=True,
    )
    actor_key = _actor_key(actor)
    body = {"object_id": str(object_id), **payload.model_dump(mode="json")}
    try:
        mutation_keys.lock_key(session, actor_key, "research.progress", key)
        existing = mutation_keys.receipt(session, actor_key, "research.progress", key, body)
        if existing is not None:
            row = session.get(SqlResearchProgressUpdate, UUID(existing.resource_ids[0]))
            if row is None:
                raise ResearchNotFound
            if commit:
                session.commit()
            return _progress_read(session, row)
        envelope = _contribution(
            session,
            actor=actor,
            target=target,
            operation="research.progress",
            required_operation=ActorOperation.CONTRIBUTION_CREATE,
            contribution=contribution,
        )
        row = SqlResearchProgressUpdate(
            ownership_scope_id=target.object.ownership_scope_id,
            object_id=object_id,
            revision_id=payload.revision_id,
            status=payload.status,
            detail_md=payload.detail_md,
            contribution_id=envelope.id,
            created_by_user_id=target.user_id,
            provenance_kind=(
                ProvenanceKind.HUMAN_DIRECT
                if actor.kind is ActorKind.HUMAN
                else ProvenanceKind.AGENT_DIRECT
            ),
        )
        session.add(row)
        session.flush()
        mutation_keys.save(session, actor_key, "research.progress", key, body, [row.id])
        if commit:
            session.commit()
            session.refresh(row)
        else:
            session.flush()
        return _progress_read(session, row)
    except Exception:
        session.rollback()
        raise


def progress_history(
    session: Session,
    *,
    actor: Actor,
    object_id: UUID,
    project_id: UUID | None,
    revision_id: UUID | None,
    limit: int,
    cursor: str | None,
) -> ResearchProgressPage:
    _target(
        session,
        actor=actor,
        object_id=object_id,
        revision_id=revision_id,
        project_id=project_id,
        write=False,
    )
    query = select(SqlResearchProgressUpdate).where(
        SqlResearchProgressUpdate.object_id == object_id
    )
    if revision_id is not None:
        query = query.where(SqlResearchProgressUpdate.revision_id == revision_id)
    if cursor:
        anchor = session.get(SqlResearchProgressUpdate, decode_cursor(cursor))
        if anchor is None or anchor.object_id != object_id:
            raise DomainConflict("invalid cursor")
        query = query.where(
            or_(
                SqlResearchProgressUpdate.created_at > anchor.created_at,
                and_(
                    SqlResearchProgressUpdate.created_at == anchor.created_at,
                    SqlResearchProgressUpdate.id > anchor.id,
                ),
            )
        )
    rows = list(
        session.scalars(
            query.order_by(
                SqlResearchProgressUpdate.created_at, SqlResearchProgressUpdate.id
            ).limit(limit + 1)
        )
    )
    return ResearchProgressPage(
        items=[_progress_read(session, row) for row in rows[:limit]],
        next_cursor=encode_cursor(rows[limit - 1].id) if len(rows) > limit else None,
    )


def _comment_read(session: Session, row: SqlResearchComment) -> ResearchCommentRead:
    author_name, actor_kind, agent_name = _attribution(
        session, row.contribution_id, row.created_by_user_id
    )
    return ResearchCommentRead(
        id=row.id,
        object_id=row.object_id,
        revision_id=row.revision_id,
        body_md=row.body_md,
        author_display_name=author_name,
        actor_kind=actor_kind,
        agent_display_name=agent_name,
        created_at=row.created_at.replace(tzinfo=UTC)
        if row.created_at.tzinfo is None
        else row.created_at.astimezone(UTC),
    )


def write_comment(
    session: Session,
    *,
    actor: Actor,
    object_id: UUID,
    payload: ResearchCommentWrite,
    key: str,
    contribution: SqlContributionEnvelope | None = None,
    commit: bool = True,
) -> ResearchCommentRead:
    target = _target(
        session,
        actor=actor,
        object_id=object_id,
        revision_id=payload.revision_id,
        project_id=payload.project_id,
        write=True,
    )
    actor_key = _actor_key(actor)
    body = {"object_id": str(object_id), **payload.model_dump(mode="json")}
    try:
        mutation_keys.lock_key(session, actor_key, "research.comment", key)
        existing = mutation_keys.receipt(session, actor_key, "research.comment", key, body)
        if existing is not None:
            row = session.get(SqlResearchComment, UUID(existing.resource_ids[0]))
            if row is None:
                raise ResearchNotFound
            if commit:
                session.commit()
            return _comment_read(session, row)
        envelope = _contribution(
            session,
            actor=actor,
            target=target,
            operation="research.comment",
            required_operation=ActorOperation.CONTRIBUTION_CREATE,
            contribution=contribution,
        )
        row = SqlResearchComment(
            ownership_scope_id=target.object.ownership_scope_id,
            object_id=object_id,
            revision_id=payload.revision_id,
            body_md=payload.body_md,
            contribution_id=envelope.id,
            created_by_user_id=target.user_id,
            provenance_kind=(
                ProvenanceKind.HUMAN_DIRECT
                if actor.kind is ActorKind.HUMAN
                else ProvenanceKind.AGENT_DIRECT
            ),
        )
        session.add(row)
        session.flush()
        mutation_keys.save(session, actor_key, "research.comment", key, body, [row.id])
        if commit:
            session.commit()
            session.refresh(row)
        else:
            session.flush()
        return _comment_read(session, row)
    except Exception:
        session.rollback()
        raise


def comment_history(
    session: Session,
    *,
    actor: Actor,
    object_id: UUID,
    project_id: UUID | None,
    revision_id: UUID | None,
    limit: int,
    cursor: str | None,
) -> ResearchCommentPage:
    _target(
        session,
        actor=actor,
        object_id=object_id,
        revision_id=revision_id,
        project_id=project_id,
        write=False,
    )
    query = select(SqlResearchComment).where(SqlResearchComment.object_id == object_id)
    if revision_id is not None:
        query = query.where(SqlResearchComment.revision_id == revision_id)
    if cursor:
        anchor = session.get(SqlResearchComment, decode_cursor(cursor))
        if anchor is None or anchor.object_id != object_id:
            raise DomainConflict("invalid cursor")
        query = query.where(
            or_(
                SqlResearchComment.created_at > anchor.created_at,
                and_(
                    SqlResearchComment.created_at == anchor.created_at,
                    SqlResearchComment.id > anchor.id,
                ),
            )
        )
    rows = list(
        session.scalars(
            query.order_by(SqlResearchComment.created_at, SqlResearchComment.id).limit(limit + 1)
        )
    )
    return ResearchCommentPage(
        items=[_comment_read(session, row) for row in rows[:limit]],
        next_cursor=encode_cursor(rows[limit - 1].id) if len(rows) > limit else None,
    )
