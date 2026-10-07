"""Scoped artifact lifecycle. Database phases never perform object-storage I/O.

Initial human uploads belong to private workspaces. Public artifact projection
is supplied by research's explicit publication integration, never by hash lookup.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor, human_actor
from polycolab.artifacts.contracts import (
    ArtifactAttachmentItem,
    ArtifactAttachmentPage,
    ArtifactRead,
    ArtifactUploadDeclaration,
    PublishedArtifactLinkRead,
    PublishedArtifactRead,
)
from polycolab.artifacts.storage import new_staging_key
from polycolab.db.converters.artifacts import artifact as _snapshot
from polycolab.db.models import (
    SqlAgentRun,
    SqlArtifact,
    SqlArtifactResearchLink,
    SqlContributionEnvelope,
    SqlExternalAgentCredential,
    SqlExternalAgentIdentity,
    SqlHostedRunArtifact,
    SqlObjectRevision,
    SqlPlatformAgentVersion,
    SqlProject,
    SqlResearchAttemptRevision,
    SqlResearchScope,
    SqlUser,
)
from polycolab.entities.artifacts import StoredArtifact as StoredArtifact
from polycolab.entities.enums import ArtifactResearchRole, ArtifactState, WorkspaceVisibility
from polycolab.entities.time import utc_now
from polycolab.platform.config import Settings
from polycolab.research.contributions import actor_contribution
from polycolab.research.objects import ResearchNotFound
from polycolab.research.records import (
    accessible_revision,
    decode_cursor,
    encode_cursor,
    project_access,
    read_condition,
)
from polycolab.workspaces.service import DomainConflict


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _scope(
    session: Session, project_id: UUID | None, user_id: UUID, *, write: bool
) -> SqlResearchScope:
    if project_id is None:
        from polycolab.catalogue.admission import lock_commons

        return lock_commons(session)
    project_access(session, project_id, user_id, write=write)
    scope = session.scalar(
        select(SqlResearchScope).where(SqlResearchScope.project_id == project_id)
    )
    if scope is None:
        raise ResearchNotFound
    return scope


def _artifact(
    session: Session, artifact_id: UUID, scope_id: UUID, *, lock: bool = False
) -> SqlArtifact:
    query = (
        select(SqlArtifact)
        .where(SqlArtifact.id == artifact_id, SqlArtifact.ownership_scope_id == scope_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    row = session.scalar(query)
    if row is None:
        raise ResearchNotFound
    return row


def reserve(
    session: Session,
    *,
    project_id: UUID | None,
    user_id: UUID,
    declaration: ArtifactUploadDeclaration,
    settings: Settings,
    source_revision_id: UUID | None = None,
    actor: Actor | None = None,
    library_destination_revision_id: UUID | None = None,
    commit: bool = True,
) -> StoredArtifact:
    """Commit identity first so ambiguous PUTs are durably discoverable by GC."""
    if declaration.byte_length > settings.artifact_max_bytes:
        raise DomainConflict("artifact exceeds configured byte limit")
    try:
        scope = _scope(session, project_id, user_id, write=True)
        if source_revision_id is not None:
            accessible_revision(session, source_revision_id, project_id)
        contribution = actor_contribution(
            session,
            actor=actor or human_actor(user_id),
            authority_user_id=user_id,
            scope_id=scope.id,
            operation="artifact.stage",
        )
        row = SqlArtifact(
            ownership_scope_id=scope.id,
            contribution_id=contribution.id,
            created_by_user_id=user_id,
            sha256=declaration.sha256,
            byte_length=declaration.byte_length,
            media_type=declaration.media_type,
            storage_key=new_staging_key(),
            source_revision_id=source_revision_id,
            library_destination_revision_id=library_destination_revision_id,
            state=ArtifactState.STAGING,
            expires_at=utc_now() + timedelta(seconds=settings.artifact_staging_ttl_seconds),
        )
        session.add(row)
        session.flush()
        result = _snapshot(row)
        if commit:
            session.commit()
        return result
    except Exception:
        session.rollback()
        raise


def verified(
    session: Session, *, project_id: UUID | None, user_id: UUID, artifact_id: UUID
) -> StoredArtifact:
    """Called only after the service adapter has verified uploaded/read-back bytes."""
    try:
        scope = _scope(session, project_id, user_id, write=True)
        row = _artifact(session, artifact_id, scope.id, lock=True)
        if session.get(SqlHostedRunArtifact, artifact_id) is not None:
            raise DomainConflict("session artifacts require an explicit new research upload")
        if row.created_by_user_id != user_id:
            raise ResearchNotFound
        if row.state != ArtifactState.STAGING or _utc(row.expires_at) <= utc_now():
            raise DomainConflict("artifact staging expired or was collected")
        if row.verified_at is None:
            row.verified_at = utc_now()
        result = _snapshot(row)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise


def read(
    session: Session,
    *,
    project_id: UUID | None,
    user_id: UUID,
    artifact_id: UUID,
    include_staging: bool = False,
) -> StoredArtifact:
    scope = _scope(session, project_id, user_id, write=False)
    row = _artifact(session, artifact_id, scope.id)
    binding = session.get(SqlHostedRunArtifact, artifact_id)
    if binding is not None:
        run = session.get(SqlAgentRun, binding.run_id)
        if run is None or run.requested_by_user_id != user_id or run.status != "COMPLETED":
            raise ResearchNotFound
    if row.state != ArtifactState.COMMITTED and not (
        include_staging
        and row.state == ArtifactState.STAGING
        and row.created_by_user_id == user_id
        and _utc(row.expires_at) > utc_now()
    ):
        raise ResearchNotFound
    return _snapshot(row)


def list_attachments(
    session: Session,
    *,
    project_id: UUID | None,
    user_id: UUID,
    revision_id: UUID | None = None,
    limit: int = 25,
    cursor: str | None = None,
) -> ArtifactAttachmentPage:
    """Page visible committed links in SQL; no object-store calls or total count."""
    scope = _scope(session, project_id, user_id, write=False)
    if revision_id is not None:
        accessible_revision(session, revision_id, project_id)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise DomainConflict("invalid artifact page limit")
    query = (
        select(SqlArtifactResearchLink, SqlArtifact)
        .join(SqlArtifact, SqlArtifact.id == SqlArtifactResearchLink.artifact_id)
        .join(SqlObjectRevision, SqlObjectRevision.id == SqlArtifactResearchLink.revision_id)
        .where(
            SqlArtifact.ownership_scope_id == scope.id,
            SqlArtifact.state == ArtifactState.COMMITTED,
            read_condition(project_id),
        )
    )
    if revision_id is not None:
        query = query.where(SqlArtifactResearchLink.revision_id == revision_id)
    if cursor is not None:
        query = query.where(SqlArtifactResearchLink.id > decode_cursor(cursor))
    rows = session.execute(query.order_by(SqlArtifactResearchLink.id).limit(limit + 1)).all()
    return ArtifactAttachmentPage(
        items=[
            ArtifactAttachmentItem(
                attachment_id=link.id,
                artifact=ArtifactRead(
                    id=artifact.id,
                    sha256=artifact.sha256,
                    byte_length=artifact.byte_length,
                    media_type=artifact.media_type,
                    state=artifact.state,
                    expires_at=artifact.expires_at,
                ),
                source_object_version_id=artifact.source_revision_id,
                object_version_id=link.revision_id,
                attempt_object_version_id=link.attempt_revision_id,
                role=link.role,
                created_at=link.created_at,
            )
            for link, artifact in rows[:limit]
        ],
        next_cursor=encode_cursor(rows[limit - 1][0].id) if len(rows) > limit else None,
    )


def attach(
    session: Session,
    *,
    project_id: UUID | None,
    user_id: UUID,
    artifact_id: UUID,
    revision_id: UUID,
    role: ArtifactResearchRole,
    attempt_revision_id: UUID | None = None,
    actor: Actor | None = None,
    commit: bool = True,
    contribution: SqlContributionEnvelope | None = None,
) -> UUID:
    """Commit verified identity and exact attachment atomically, reauthorizing retries.

    Project/membership locks precede the artifact row lock. Holding the artifact
    row also serializes nullable-attempt duplicate bindings on PostgreSQL.
    """
    try:
        scope = _scope(session, project_id, user_id, write=True)
        accessible_revision(session, revision_id, project_id)
        if attempt_revision_id is not None:
            attempt_revision = accessible_revision(session, attempt_revision_id, project_id)
            attempt = session.get(SqlResearchAttemptRevision, attempt_revision.id)
            if attempt is None or attempt.target_revision_id != revision_id:
                raise DomainConflict("attempt must target the exact attached revision")
            if attempt_revision.ownership_scope_id != scope.id:
                raise ResearchNotFound
        row = _artifact(session, artifact_id, scope.id, lock=True)
        if session.get(SqlHostedRunArtifact, artifact_id) is not None:
            raise DomainConflict("session artifacts require an explicit new research upload")
        if row.state == ArtifactState.STAGING:
            if row.created_by_user_id != user_id:
                raise ResearchNotFound
            if row.verified_at is None or _utc(row.expires_at) <= utc_now():
                raise DomainConflict("artifact is unverified or expired")
            row.state = ArtifactState.COMMITTED
            row.committed_at = utc_now()
            session.flush()
        elif row.state != ArtifactState.COMMITTED:
            raise DomainConflict("artifact is no longer available for commit")
        existing = session.scalar(
            select(SqlArtifactResearchLink).where(
                SqlArtifactResearchLink.artifact_id == artifact_id,
                SqlArtifactResearchLink.revision_id == revision_id,
                SqlArtifactResearchLink.attempt_revision_id == attempt_revision_id,
                SqlArtifactResearchLink.role == role,
            )
        )
        if existing is not None:
            result = existing.id
        else:
            contribution = contribution or actor_contribution(
                session,
                actor=actor or human_actor(user_id),
                authority_user_id=user_id,
                scope_id=scope.id,
                operation="artifact.attach",
            )
            link = SqlArtifactResearchLink(
                artifact_id=artifact_id,
                revision_id=revision_id,
                attempt_revision_id=attempt_revision_id,
                role=role,
                contribution_id=contribution.id,
                created_by_user_id=user_id,
            )
            session.add(link)
            session.flush()
            result = link.id
        if commit:
            session.commit()
        else:
            session.flush()
        return result
    except Exception:
        session.rollback()
        raise


def public_artifact(
    session: Session, artifact_id: UUID
) -> tuple[SqlArtifact, PublishedArtifactRead]:
    """Project only committed bytes attached to active public-workspace research."""

    artifact = session.get(SqlArtifact, artifact_id)
    if artifact is None or artifact.state is not ArtifactState.COMMITTED:
        raise ResearchNotFound
    scope = session.get(SqlResearchScope, artifact.ownership_scope_id)
    project = session.get(SqlProject, scope.project_id) if scope and scope.project_id else None
    if scope is None or (
        scope.project_id is not None
        and (
            project is None
            or project.visibility is not WorkspaceVisibility.PUBLIC
            or project.archived_at is not None
            or project.deleted_at is not None
        )
    ):
        raise ResearchNotFound
    links: list[SqlArtifactResearchLink] = []
    for link in session.scalars(
        select(SqlArtifactResearchLink)
        .where(SqlArtifactResearchLink.artifact_id == artifact.id)
        .order_by(SqlArtifactResearchLink.created_at, SqlArtifactResearchLink.id)
    ):
        try:
            from polycolab.research.records import public_revision

            public_revision(session, link.revision_id)
        except ResearchNotFound:
            continue
        links.append(link)
    if not links:
        raise ResearchNotFound
    author = session.get(SqlUser, artifact.created_by_user_id)
    envelope = session.get(SqlContributionEnvelope, artifact.contribution_id)
    if author is None or envelope is None:
        raise ResearchNotFound
    agent_name = None
    if envelope.agent_version_id is not None:
        agent = session.get(SqlPlatformAgentVersion, envelope.agent_version_id)
        agent_name = agent.display_name if agent is not None else None
    elif envelope.external_credential_id is not None:
        credential = session.get(SqlExternalAgentCredential, envelope.external_credential_id)
        identity = (
            session.get(SqlExternalAgentIdentity, credential.agent_id)
            if credential and credential.agent_id
            else None
        )
        agent_name = identity.name if identity else None
    return artifact, PublishedArtifactRead(
        id=artifact.id,
        sha256=artifact.sha256,
        byte_length=artifact.byte_length,
        media_type=artifact.media_type,
        source_revision_id=artifact.source_revision_id,
        links=[
            PublishedArtifactLinkRead(
                revision_id=link.revision_id,
                attempt_revision_id=link.attempt_revision_id,
                role=link.role,
            )
            for link in links
        ],
        author_display_name=author.display_name,
        actor_kind=envelope.actor_kind.value,
        agent_display_name=agent_name,
        created_at=artifact.created_at,
        content_path=f"/api/v1/artifacts/{artifact.id}/content",
    )


def list_public_attachments(
    session: Session,
    *,
    project_id: UUID | None,
    revision_id: UUID | None = None,
    limit: int = 25,
    cursor: str | None = None,
) -> ArtifactAttachmentPage:
    project = session.get(SqlProject, project_id)
    if (
        project is None
        or project.visibility is not WorkspaceVisibility.PUBLIC
        or project.archived_at is not None
        or project.deleted_at is not None
    ):
        raise ResearchNotFound
    scope = session.scalar(
        select(SqlResearchScope).where(SqlResearchScope.project_id == project_id)
    )
    if scope is None:
        raise ResearchNotFound
    if revision_id is not None:
        from polycolab.research.records import public_revision

        revision = public_revision(session, revision_id)
        if revision.project_id != project_id:
            raise ResearchNotFound
    query = (
        select(SqlArtifactResearchLink, SqlArtifact)
        .join(SqlArtifact, SqlArtifact.id == SqlArtifactResearchLink.artifact_id)
        .join(SqlObjectRevision, SqlObjectRevision.id == SqlArtifactResearchLink.revision_id)
        .where(
            SqlArtifact.ownership_scope_id == scope.id,
            SqlArtifact.state == ArtifactState.COMMITTED,
            SqlObjectRevision.project_id == project_id,
        )
    )
    if revision_id is not None:
        query = query.where(SqlArtifactResearchLink.revision_id == revision_id)
    if cursor is not None:
        query = query.where(SqlArtifactResearchLink.id > decode_cursor(cursor))
    rows = session.execute(query.order_by(SqlArtifactResearchLink.id).limit(limit + 1)).all()
    visible: list[tuple[SqlArtifactResearchLink, SqlArtifact]] = []
    for link, artifact in rows:
        try:
            public_artifact(session, artifact.id)
        except ResearchNotFound:
            continue
        visible.append((link, artifact))
    selected = visible[:limit]
    return ArtifactAttachmentPage(
        items=[
            ArtifactAttachmentItem(
                attachment_id=link.id,
                artifact=ArtifactRead(
                    id=artifact.id,
                    sha256=artifact.sha256,
                    byte_length=artifact.byte_length,
                    media_type=artifact.media_type,
                    state=artifact.state,
                    expires_at=artifact.expires_at,
                ),
                source_object_version_id=artifact.source_revision_id,
                object_version_id=link.revision_id,
                attempt_object_version_id=link.attempt_revision_id,
                role=link.role,
                created_at=link.created_at,
            )
            for link, artifact in selected
        ],
        next_cursor=encode_cursor(selected[-1][0].id) if len(visible) > limit else None,
    )
