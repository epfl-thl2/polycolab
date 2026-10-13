"""Atomic project imports and append-only, explicitly upgraded public pins."""

from datetime import UTC
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor
from polycolab.access.authorization import require_human_actor
from polycolab.catalogue.admission import lock_commons
from polycolab.db.models import (
    SqlCatalogueEntry,
    SqlMembership,
    SqlMutationReceipt,
    SqlProject,
    SqlProjectReference,
    SqlProjectReferenceVersion,
    SqlResearchScope,
    SqlUser,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import ProjectRole, ProjectVisibility
from polycolab.platform import mutation_keys
from polycolab.platform.outbox import append_event
from polycolab.projects.service import DomainConflict, create_project
from polycolab.research import records
from polycolab.research.contracts import (
    ProjectReferenceCreate,
    ProjectReferencePage,
    ProjectReferenceRead,
    ProjectReferenceUpgrade,
)
from polycolab.research.objects import ResearchNotFound


def latest(session: Session, reference_id: UUID) -> SqlProjectReferenceVersion:
    value = session.scalar(
        select(SqlProjectReferenceVersion)
        .where(SqlProjectReferenceVersion.reference_id == reference_id)
        .order_by(SqlProjectReferenceVersion.number.desc())
        .limit(1)
    )
    assert value is not None
    return value


def read(
    session: Session, reference: SqlProjectReference, version: SqlProjectReferenceVersion
) -> ProjectReferenceRead:
    try:
        revision = records.public_revision(session, version.revision_id)
        title = revision.title
        available = True
    except ResearchNotFound:
        title, available = None, False
    entry = session.get(SqlCatalogueEntry, reference.object_id) if available else None
    return ProjectReferenceRead(
        id=reference.id,
        project_id=reference.project_id,
        object_id=reference.object_id,
        reference_version_id=version.id,
        number=version.number,
        previous_reference_version_id=version.base_version_id,
        object_version_id=version.revision_id,
        available=available,
        title=title,
        reason=version.reason,
        created_at=version.created_at.replace(tzinfo=UTC),
        latest_object_version_id=entry.official_revision_id if entry and not entry.hidden else None,
    )


def append_version(
    session: Session,
    reference: SqlProjectReference,
    *,
    user_id: UUID,
    revision_id: UUID,
    reason: str,
    base: SqlProjectReferenceVersion | None,
) -> SqlProjectReferenceVersion:
    version = SqlProjectReferenceVersion(
        reference_id=reference.id,
        revision_id=revision_id,
        created_by_user_id=user_id,
        number=base.number + 1 if base else 1,
        base_version_id=base.id if base else None,
        reason=reason,
    )
    session.add(version)
    session.flush()
    scope = session.scalar(
        select(SqlResearchScope).where(SqlResearchScope.project_id == reference.project_id)
    )
    assert scope is not None
    append_event(
        session,
        event_type="project.reference.updated",
        aggregate_type="project_reference",
        aggregate_id=reference.id,
        ownership_scope_id=scope.id,
        payload={"reference_id": str(reference.id), "version_id": str(version.id)},
    )
    return version


def create(
    session: Session,
    *,
    actor: Actor,
    payload: ProjectReferenceCreate,
    key: str,
) -> ProjectReferenceRead:
    require_human_actor(actor, action="import public research")
    user_id = actor.human_user_id
    assert user_id is not None
    actor_key = f"human:{user_id}"
    body = payload.model_dump(mode="json")
    if "project_name" not in payload.model_fields_set:
        # Historical default belongs only to retry serialization, never new names.
        body["project_name"] = "Research workspace"
    body["revision_id"] = body.pop("object_version_id")
    # The legacy private-reference API retains its existing retry digest.
    if body["project_visibility"] == "PRIVATE":
        body.pop("project_visibility")
    if not body["create_new_project"]:
        body.pop("create_new_project")

    def authorize_retry(stored: SqlMutationReceipt) -> None:
        reference = session.get(SqlProjectReference, UUID(stored.resource_ids[0]))
        if reference is None:
            raise ResearchNotFound
        records.project_access(session, reference.project_id, user_id, write=True)

    try:
        mutation_keys.lock_key(session, actor_key, "reference.create", key)
        # Serialize automatic project selection across different invocation keys.
        mutation_keys.lock_key(session, actor_key, "reference.selection", "project")
        receipt = mutation_keys.receipt(
            session,
            actor_key,
            "reference.create",
            key,
            body,
            authorize=authorize_retry,
        )
        if receipt is not None:
            reference = session.get(SqlProjectReference, UUID(receipt.resource_ids[0]))
            version = session.get(SqlProjectReferenceVersion, UUID(receipt.resource_ids[1]))
            assert reference is not None and version is not None
            records.project_access(session, reference.project_id, user_id, write=True)
            lock_commons(session)
            records.public_revision(session, payload.object_version_id)
        else:
            # Resolve identity before selecting a project; visibility is checked
            # again under the commons lock after the project authorization lock.
            target = records.public_revision(session, payload.object_version_id)
            project_id = payload.project_id
            if project_id is None and not payload.create_new_project:
                project_id = session.scalar(
                    select(SqlProjectReference.project_id)
                    .join(SqlProject, SqlProject.id == SqlProjectReference.project_id)
                    .join(SqlMembership, SqlMembership.project_id == SqlProject.id)
                    .where(
                        SqlProjectReference.object_id == target.object_id,
                        SqlProjectReference.created_by_user_id == user_id,
                        SqlMembership.user_id == user_id,
                        SqlMembership.role.in_([ProjectRole.OWNER, ProjectRole.CONTRIBUTOR]),
                        SqlProject.archived_at.is_(None),
                        SqlProject.visibility == ProjectVisibility(payload.project_visibility),
                    )
                    .order_by(SqlProjectReference.id)
                    .limit(1)
                )
            if project_id is None:
                user = session.get(SqlUser, user_id)
                assert user is not None
                project_id = create_project(
                    SqlAlchemyTransaction(session),
                    creator=user,
                    name=payload.project_name,
                    description=None,
                    visibility=ProjectVisibility(payload.project_visibility),
                    commit=False,
                ).id
            records.project_access(session, project_id, user_id, write=True)
            lock_commons(session)
            target = records.public_revision(session, payload.object_version_id)
            reference = session.scalar(
                select(SqlProjectReference)
                .where(
                    SqlProjectReference.project_id == project_id,
                    SqlProjectReference.object_id == target.object_id,
                )
                .with_for_update()
            )
            if reference is None:
                reference = SqlProjectReference(
                    project_id=project_id,
                    object_id=target.object_id,
                    created_by_user_id=user_id,
                )
                session.add(reference)
                session.flush()
                version = append_version(
                    session,
                    reference,
                    user_id=user_id,
                    revision_id=target.id,
                    reason=payload.reason,
                    base=None,
                )
            else:
                version = latest(session, reference.id)
                if version.revision_id != target.id:
                    raise DomainConflict("reference exists at another revision; upgrade explicitly")
            mutation_keys.save(
                session, actor_key, "reference.create", key, body, [reference.id, version.id]
            )
        result = read(session, reference, version)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise


def upgrade(
    session: Session,
    *,
    actor: Actor,
    reference_id: UUID,
    payload: ProjectReferenceUpgrade,
    key: str,
) -> ProjectReferenceRead:
    require_human_actor(actor, action="reference upgrade")
    user_id = actor.human_user_id
    assert user_id is not None
    actor_key = f"human:{user_id}"
    body = {"reference_id": str(reference_id), **payload.model_dump(mode="json")}
    # Keep persisted retry digests independent of the live field names.
    body["revision_id"] = body.pop("object_version_id")
    body["base_version_id"] = body.pop("expected_current_reference_version_id")
    try:
        mutation_keys.lock_key(session, actor_key, "reference.upgrade", key)
        reference = session.get(SqlProjectReference, reference_id)
        if reference is None:
            raise ResearchNotFound
        records.project_access(session, reference.project_id, user_id, write=True)
        lock_commons(session)
        session.execute(
            select(SqlProjectReference.id)
            .where(SqlProjectReference.id == reference_id)
            .with_for_update()
        )
        target = records.public_revision(session, payload.object_version_id)
        if target.object_id != reference.object_id:
            raise DomainConflict("reference upgrades must preserve target identity")
        receipt = mutation_keys.receipt(session, actor_key, "reference.upgrade", key, body)
        if receipt is not None:
            version = session.get(SqlProjectReferenceVersion, UUID(receipt.resource_ids[0]))
            assert version is not None
        else:
            base = latest(session, reference.id)
            if base.id != payload.expected_current_reference_version_id:
                raise DomainConflict("stale reference base")
            version = append_version(
                session,
                reference,
                user_id=user_id,
                revision_id=target.id,
                reason=payload.reason,
                base=base,
            )
            mutation_keys.save(session, actor_key, "reference.upgrade", key, body, [version.id])
        result = read(session, reference, version)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise


def page(
    session: Session,
    *,
    project_id: UUID,
    user_id: UUID,
    reference_id: UUID | None,
    limit: int,
    cursor: str | None,
) -> ProjectReferencePage:
    records.project_access(session, project_id, user_id)
    if reference_id is None:
        query = select(SqlProjectReference).where(SqlProjectReference.project_id == project_id)
        if cursor:
            query = query.where(SqlProjectReference.id > records.decode_cursor(cursor))
        rows = list(session.scalars(query.order_by(SqlProjectReference.id).limit(limit + 1)))
        return ProjectReferencePage(
            items=[read(session, row, latest(session, row.id)) for row in rows[:limit]],
            next_cursor=records.encode_cursor(rows[limit - 1].id) if len(rows) > limit else None,
        )
    reference = session.get(SqlProjectReference, reference_id)
    if reference is None or reference.project_id != project_id:
        raise ResearchNotFound
    history = select(SqlProjectReferenceVersion).where(
        SqlProjectReferenceVersion.reference_id == reference_id
    )
    if cursor:
        history = history.where(SqlProjectReferenceVersion.id > records.decode_cursor(cursor))
    versions = list(
        session.scalars(history.order_by(SqlProjectReferenceVersion.id).limit(limit + 1))
    )
    return ProjectReferencePage(
        items=[read(session, reference, version) for version in versions[:limit]],
        next_cursor=records.encode_cursor(versions[limit - 1].id)
        if len(versions) > limit
        else None,
    )
