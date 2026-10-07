"""Scoped typed research, exact attachments, and permission-filtered reads."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from polycolab.access.actors import Actor, ActorKind, ActorOperation
from polycolab.access.authorization import (
    AuthorizationDenied,
    WorkspaceAction,
    lock_workspace_authorization,
    require_human_actor,
    workspace_policy,
)
from polycolab.catalogue.admission import is_moderator, lock_commons
from polycolab.catalogue.schemas import CatalogueRevise
from polycolab.db.models import (
    SqlCatalogueEntry,
    SqlCatalogueRevision,
    SqlContributionEnvelope,
    SqlCorrectionSuggestion,
    SqlObjectRevision,
    SqlProject,
    SqlPublicationRelation,
    SqlPublicRelease,
    SqlPublicResearchAnchor,
    SqlRecordModeration,
    SqlRecordRevision,
    SqlRelationAssertion,
    SqlResearchAttachment,
    SqlResearchObject,
    SqlResearchScope,
    SqlStatementRevision,
)
from polycolab.db.stores.relationships import add_declaration, add_structural_relationship
from polycolab.db.stores.research import SqlResearchReadStore
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import (
    CanonicalEntityType,
    ContributionActorKind,
    ProvenanceKind,
    RelationType,
    ResearchEntityClass,
    WorkspaceVisibility,
)
from polycolab.entities.object_kinds import canonical_kind
from polycolab.entities.research import (
    KIND_DEFINITIONS,
    AttemptVersion,
    ProofSketchVersion,
    StructuralRole,
)
from polycolab.platform import mutation_keys
from polycolab.platform.outbox import canonical_digest
from polycolab.research.contracts import (
    ObjectVersionDisplayBatchRead,
    ObjectVersionDisplayRead,
    ObjectVersionDisplayRequest,
    RecordPage,
    RecordRead,
    RecordWrite,
    ResourceResult,
    ScopedRelationWrite,
)
from polycolab.research.contributions import human_contribution, link_output
from polycolab.research.objects import ResearchNotFound
from polycolab.workspaces.service import DomainConflict


def _provenance_kind(envelope: SqlContributionEnvelope) -> ProvenanceKind:
    if envelope.actor_kind is ContributionActorKind.HUMAN:
        return ProvenanceKind.HUMAN_DIRECT
    if envelope.proposal_change_id is not None:
        return ProvenanceKind.AGENT_PROPOSAL
    return ProvenanceKind.AGENT_DIRECT


def public_condition(
    revision_id: ColumnElement[UUID] | InstrumentedAttribute[UUID],
) -> ColumnElement[bool]:
    released = exists(
        select(SqlPublicRelease.id).where(SqlPublicRelease.object_revision_id == revision_id)
    )
    selectively_published = exists(
        select(SqlPublicRelease.id).where(
            SqlPublicRelease.object_revision_id == revision_id,
            SqlPublicRelease.publication_manifest_id.is_not(None),
        )
    )
    official = exists(
        select(SqlCatalogueRevision.revision_id)
        .join(SqlCatalogueEntry, SqlCatalogueEntry.id == SqlCatalogueRevision.entry_id)
        .where(SqlCatalogueRevision.revision_id == revision_id, SqlCatalogueEntry.hidden.is_(False))
    )
    anchored = exists(
        select(SqlPublicResearchAnchor.entry_id).where(
            SqlPublicResearchAnchor.revision_id == revision_id
        )
    )
    hidden = exists(
        select(SqlPublicResearchAnchor.entry_id)
        .join(SqlCatalogueEntry, SqlCatalogueEntry.id == SqlPublicResearchAnchor.entry_id)
        .where(
            SqlPublicResearchAnchor.revision_id == revision_id, SqlCatalogueEntry.hidden.is_(True)
        )
    )
    candidate = aliased(SqlObjectRevision)
    record_hidden = exists(
        select(SqlRecordModeration.object_id)
        .join(candidate, candidate.object_id == SqlRecordModeration.object_id)
        .where(candidate.id == revision_id, SqlRecordModeration.hidden.is_(True))
    )
    workspace_revision = aliased(SqlObjectRevision)
    public_workspace = exists(
        select(SqlProject.id)
        .join(workspace_revision, workspace_revision.project_id == SqlProject.id)
        .where(
            workspace_revision.id == revision_id,
            SqlProject.visibility == WorkspaceVisibility.PUBLIC,
            SqlProject.archived_at.is_(None),
            SqlProject.deleted_at.is_(None),
        )
    )
    return and_(
        ~record_hidden,
        or_(
            public_workspace,
            and_(released, or_(selectively_published, official, and_(anchored, ~hidden))),
        ),
    )


def public_revision(session: Session, revision_id: UUID) -> SqlObjectRevision:
    value = session.scalar(
        select(SqlObjectRevision).where(
            SqlObjectRevision.id == revision_id, public_condition(SqlObjectRevision.id)
        )
    )
    if value is None:
        raise ResearchNotFound
    return value


def accessible_revision(
    session: Session, revision_id: UUID, project_id: UUID | None
) -> SqlObjectRevision:
    value = session.get(SqlObjectRevision, revision_id)
    if value is None:
        raise ResearchNotFound
    if project_id is not None and value.project_id == project_id:
        return value
    return public_revision(session, revision_id)


def read_condition(project_id: UUID | None) -> ColumnElement[bool]:
    return (
        public_condition(SqlObjectRevision.id)
        if project_id is None
        else or_(SqlObjectRevision.project_id == project_id, public_condition(SqlObjectRevision.id))
    )


def relation_read_condition(project_id: UUID | None) -> ColumnElement[bool]:
    """Relationship scope and both pins must be visible; public pins alone are insufficient."""
    public_scope = exists(
        select(SqlResearchScope.id)
        .outerjoin(SqlProject, SqlProject.id == SqlResearchScope.project_id)
        .where(
            SqlResearchScope.id == SqlRelationAssertion.ownership_scope_id,
            or_(
                SqlResearchScope.project_id.is_(None),
                and_(
                    SqlProject.visibility == WorkspaceVisibility.PUBLIC,
                    SqlProject.archived_at.is_(None),
                    SqlProject.deleted_at.is_(None),
                ),
            ),
        )
    )
    released = exists(
        select(SqlPublicationRelation.relation_id).where(
            SqlPublicationRelation.relation_id == SqlRelationAssertion.id
        )
    )
    allowed_scope = or_(public_scope, released)
    if project_id is not None:
        allowed_scope = or_(allowed_scope, SqlRelationAssertion.project_id == project_id)
    return and_(
        allowed_scope,
        *(
            exists(
                select(SqlObjectRevision.id).where(
                    SqlObjectRevision.id == endpoint, read_condition(project_id)
                )
            )
            for endpoint in (
                SqlRelationAssertion.source_revision_id,
                SqlRelationAssertion.target_revision_id,
            )
        ),
    )


def encode_cursor(value: UUID) -> str:
    return base64.urlsafe_b64encode(f"v1:{value}".encode()).decode()


def decode_cursor(value: str) -> UUID:
    try:
        version, raw = base64.b64decode(value, altchars=b"-_", validate=True).decode().split(":", 1)
        if version != "v1":
            raise ValueError
        return UUID(raw)
    except ValueError, UnicodeError, binascii.Error:
        raise DomainConflict("invalid cursor") from None


def project_access(
    session: Session, project_id: UUID, user_id: UUID, *, write: bool = False
) -> None:
    if write:
        lock_workspace_authorization(
            SqlAlchemyTransaction(session), project_id=project_id, user_id=user_id
        )
    workspace_policy.require_scope(
        SqlAlchemyTransaction(session),
        project_id,
        user_id,
        WorkspaceAction.CREATE_RESEARCH if write else WorkspaceAction.VIEW,
    )


def record_read(
    session: Session,
    revision: SqlObjectRevision,
    project_id: UUID | None = None,
) -> RecordRead:
    return record_reads(session, [revision], project_id)[0]


def record_reads(
    session: Session, revisions: Sequence[SqlObjectRevision], project_id: UUID | None = None
) -> list[RecordRead]:
    """Complete selected snapshots, with child and metadata queries batched."""
    from polycolab.catalogue.schemas import CatalogueSource
    from polycolab.research.schemas import (
        AttemptEvidenceRead,
        ProofStructureRead,
        ResearchAttemptStructureRead,
    )

    ids = [revision.id for revision in revisions]
    snapshots = SqlResearchReadStore(session).versions(ids)
    formulations = {
        row.revision_id: row
        for row in session.scalars(
            select(SqlCatalogueRevision).where(SqlCatalogueRevision.revision_id.in_(ids))
        )
    }
    suggestions = {
        row.revision_id: row
        for row in session.scalars(
            select(SqlCorrectionSuggestion).where(SqlCorrectionSuggestion.revision_id.in_(ids))
        )
    }
    bases = {snapshot.previous_object_version_id for snapshot in snapshots.values()} - {None}
    dependencies = {
        relationship.target_object_version_id
        for snapshot in snapshots.values()
        if project_id is None or isinstance(snapshot, (ProofSketchVersion, AttemptVersion))
        for relationship in snapshot.structural_relationships
    }
    visible = set(
        session.scalars(
            select(SqlObjectRevision.id).where(
                SqlObjectRevision.id.in_(bases | dependencies), read_condition(project_id)
            )
        )
    )
    if not dependencies.issubset(visible):
        raise ResearchNotFound
    result = []
    for revision in revisions:
        snapshot = snapshots[revision.id]
        formulation = formulations.get(revision.id)
        suggestion = suggestions.get(revision.id)
        attribution = snapshot.authorship
        proof = (
            ProofStructureRead(
                sketch_revision_id=snapshot.id,
                conclusion_revision_id=snapshot.conclusion_object_version_id,
                premise_revision_ids=list(snapshot.premise_object_version_ids),
                reported_progress=snapshot.content.reported_progress,
            )
            if isinstance(snapshot, ProofSketchVersion)
            and snapshot.conclusion_object_version_id is not None
            and snapshot.content.reported_progress is not None
            else None
        )
        attempt = (
            ResearchAttemptStructureRead(
                attempt_revision_id=snapshot.id,
                target_object_id=snapshot.target_object_id,
                target_revision_id=snapshot.target_object_version_id,
                outcome=snapshot.content.outcome,
                findings_md=snapshot.content.findings_md,
                result_revision_id=snapshot.result_object_version_id,
                evidence=[
                    AttemptEvidenceRead(revision_id=item.object_version_id, role=item.role)
                    for item in snapshot.evidence
                ],
            )
            if isinstance(snapshot, AttemptVersion)
            and snapshot.target_object_id is not None
            and snapshot.target_object_version_id is not None
            and snapshot.content.outcome is not None
            and snapshot.content.findings_md is not None
            else None
        )
        result.append(
            RecordRead(
                catalogue_entry_id=formulation.entry_id if formulation else None,
                catalogue_source=CatalogueSource(
                    identifier=formulation.source_identifier,
                    version=formulation.source_version,
                    locator=formulation.source_locator,
                )
                if formulation
                and formulation.source_identifier
                and formulation.source_version
                and formulation.source_locator
                else None,
                catalogue_reported_status=formulation.reported_status if formulation else None,
                suggestion=CatalogueRevise.model_validate(suggestion.proposed)
                if suggestion
                else None,
                object_id=snapshot.object_id,
                revision_id=snapshot.id,
                number=snapshot.number,
                base_revision_id=snapshot.previous_object_version_id
                if snapshot.previous_object_version_id in visible
                else None,
                kind=snapshot.kind,
                semantic_metadata=revision.semantic_metadata,
                title=snapshot.content.title,
                content_md=snapshot.content.content_md,
                schema_version=snapshot.schema_version,
                rationale=snapshot.change_summary,
                assumptions_md=snapshot.content.assumptions_md,
                statement_revision_ids=list(snapshot.statement_object_version_ids),
                reported_outcome=snapshot.content.reported_outcome,
                explanation_md=snapshot.content.explanation_md,
                proof_sketch=proof,
                attempt=attempt,
                author_display_name=attribution.author_display_name,
                actor_kind=attribution.actor_kind.value,
                author_user_id=attribution.author_user_id,
                agent_id=attribution.agent_id,
                sponsor_user_id=attribution.sponsor_user_id,
                agent_display_name=attribution.agent_display_name,
                created_at=snapshot.created_at,
            )
        )
    return result


def visible_base_revision_id(
    session: Session, revision_id: UUID | None, project_id: UUID | None = None
) -> UUID | None:
    """Project scope must already be authorized by the caller."""
    if revision_id is None:
        return None
    return session.scalar(
        select(SqlObjectRevision.id).where(
            SqlObjectRevision.id == revision_id, read_condition(project_id)
        )
    )


def public_record_read(session: Session, revision: SqlObjectRevision) -> RecordRead:
    """Return the immutable released projection after rechecking exact dependencies."""
    return public_record_reads(session, [revision])[0]


def public_record_reads(
    session: Session, revisions: Sequence[SqlObjectRevision]
) -> list[RecordRead]:
    from polycolab.catalogue.schemas import PublicStatementRead

    ids = {revision.id for revision in revisions}
    visible = set(
        session.scalars(
            select(SqlObjectRevision.id).where(
                SqlObjectRevision.id.in_(ids), public_condition(SqlObjectRevision.id)
            )
        )
    )
    if visible != ids:
        raise ResearchNotFound
    releases = {
        release.object_revision_id: release
        for release in session.scalars(
            select(SqlPublicRelease).where(SqlPublicRelease.object_revision_id.in_(ids))
        )
    }
    result = []
    for current in record_reads(session, revisions):
        release = releases.get(current.revision_id)
        if release is None:
            result.append(current)
        elif release.projection_version == 1:
            saved_statement = PublicStatementRead.model_validate(release.public_fields)
            if (
                saved_statement.revision_id != current.revision_id
                or saved_statement.object_id != current.object_id
                or saved_statement.kind != current.kind
            ):
                raise ResearchNotFound
            result.append(
                current.model_copy(
                    update={
                        **saved_statement.model_dump(exclude={"kind"}),
                        # Format 1 released display names, not account identities.
                        "author_user_id": None,
                        "agent_id": None,
                        "sponsor_user_id": None,
                    }
                )
            )
        elif release.projection_version in {2, 3, 4, 5}:
            saved = RecordRead.model_validate(release.public_fields)
            if saved.revision_id != current.revision_id or saved.object_id != current.object_id:
                raise ResearchNotFound
            result.append(
                saved.model_copy(
                    update={
                        "base_revision_id": saved.base_revision_id
                        if saved.base_revision_id == current.base_revision_id
                        else None,
                    }
                )
            )
        else:
            raise ResearchNotFound
    return result


def object_version_displays(
    session: Session, payload: ObjectVersionDisplayRequest
) -> ObjectVersionDisplayBatchRead:
    rows = list(
        session.execute(
            select(SqlObjectRevision, SqlResearchObject)
            .join(SqlResearchObject, SqlResearchObject.id == SqlObjectRevision.object_id)
            .where(
                SqlObjectRevision.id.in_(payload.object_version_ids),
                read_condition(payload.project_id),
            )
        )
    )
    member_rows = [
        row for row, _ in rows if payload.project_id and row.project_id == payload.project_id
    ]
    public_rows = [
        row for row, _ in rows if not payload.project_id or row.project_id != payload.project_id
    ]
    selected = record_reads(session, member_rows, payload.project_id) + public_record_reads(
        session, public_rows
    )
    by_id = {
        version.revision_id: ObjectVersionDisplayRead(
            object_version_id=version.revision_id,
            object_id=version.object_id,
            kind=canonical_kind(version.kind),
            title=version.title,
        )
        for version in selected
    }
    if len(by_id) != len(payload.object_version_ids):
        raise ResearchNotFound
    return ObjectVersionDisplayBatchRead(
        items=[by_id[value] for value in payload.object_version_ids]
    )


def list_records(
    session: Session,
    *,
    project_id: UUID | None,
    statement_id: UUID | None,
    object_id: UUID | None = None,
    limit: int = 25,
    cursor: str | None = None,
) -> RecordPage:
    query = select(SqlObjectRevision).join(
        SqlResearchObject, SqlResearchObject.id == SqlObjectRevision.object_id
    )
    query = query.where(read_condition(project_id))
    if object_id is not None:
        query = query.where(SqlObjectRevision.object_id == object_id)
    else:
        query = query.where(SqlResearchObject.current_revision_id == SqlObjectRevision.id)
        if project_id is not None:
            query = query.where(SqlObjectRevision.project_id == project_id)
    if statement_id is not None:
        query = query.where(
            exists(
                select(SqlResearchAttachment.revision_id).where(
                    SqlResearchAttachment.revision_id == SqlObjectRevision.id,
                    SqlResearchAttachment.statement_revision_id == statement_id,
                )
            )
        )
    if project_id is None and object_id is None:
        query = query.where(
            exists(
                select(SqlResearchAttachment.revision_id).where(
                    SqlResearchAttachment.revision_id == SqlObjectRevision.id
                )
            )
        )
    if cursor:
        query = query.where(SqlObjectRevision.id > decode_cursor(cursor))
    values = list(session.scalars(query.order_by(SqlObjectRevision.id).limit(limit + 1)))
    return RecordPage(
        items=[
            public_record_read(session, row)
            if project_id is None
            else record_read(session, row, project_id)
            for row in values[:limit]
        ],
        next_cursor=encode_cursor(values[limit - 1].id) if len(values) > limit else None,
    )


def write_record(
    session: Session,
    *,
    actor: Actor,
    payload: RecordWrite,
    key: str,
    contribution: SqlContributionEnvelope | None = None,
    commit: bool = True,
) -> ResourceResult:
    from polycolab.research.contracts import SnapshotRecordWrite

    if actor.kind == ActorKind.AGENT:
        operation = (
            ActorOperation.CONTRIBUTION_EDIT
            if payload.object_id
            else ActorOperation.CONTRIBUTION_CREATE
        )
        if (
            contribution is None
            or operation not in actor.operation_scope
            or contribution.run_id != actor.run_id
        ):
            raise AuthorizationDenied("missing validated contribution authority")
    else:
        require_human_actor(actor, action="research contribution")
    user_id = actor.human_user_id if actor.kind == ActorKind.HUMAN else actor.sponsor_user_id
    assert user_id is not None
    actor_key = (
        f"human:{user_id}"
        if actor.kind == ActorKind.HUMAN
        else f"agent:{actor.external_agent_id or actor.external_run_id or actor.run_id}"
    )
    body = payload.model_dump(mode="json")
    try:
        mutation_keys.lock_key(session, actor_key, "record.write", key)
        if payload.project_id is not None:
            project_access(session, payload.project_id, user_id, write=True)
        commons = lock_commons(session)
        scope = (
            commons
            if payload.project_id is None
            else session.scalar(
                select(SqlResearchScope).where(SqlResearchScope.project_id == payload.project_id)
            )
        )
        assert scope is not None
        if payload.proof_sketch is not None:
            from polycolab.research.proofs import validate_structure

            validate_structure(
                session,
                project_id=payload.project_id,
                kind=payload.kind,
                payload=payload.proof_sketch,
            )
        if isinstance(payload, SnapshotRecordWrite) and payload.proof_sketch is not None:
            target_kind = session.scalar(
                select(SqlResearchObject.kind)
                .join(SqlObjectRevision, SqlObjectRevision.object_id == SqlResearchObject.id)
                .where(SqlObjectRevision.id == payload.proof_sketch.conclusion_revision_id)
            )
            if target_kind is None or canonical_kind(target_kind).value != "STATEMENT":
                raise DomainConflict("a proof must support or refute an exact statement")
        if contribution is not None and contribution.ownership_scope_id != scope.id:
            raise AuthorizationDenied("contribution destination mismatch")
        obj = (
            session.scalar(
                select(SqlResearchObject)
                .where(SqlResearchObject.id == payload.object_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if payload.object_id
            else None
        )
        if payload.object_id is not None:
            if obj is None or obj.ownership_scope_id != scope.id:
                raise ResearchNotFound
            moderation = session.get(SqlRecordModeration, obj.id, populate_existing=True)
            if moderation is not None and moderation.hidden:
                raise AuthorizationDenied("restore the moderated contribution before editing")
            if session.get(SqlCatalogueEntry, obj.id) is not None:
                raise AuthorizationDenied(
                    "official edits require catalogue authority; suggest a correction"
                )
            if actor.kind == ActorKind.HUMAN and obj.created_by_user_id != user_id:
                if payload.project_id is not None or not is_moderator(session, user_id):
                    raise AuthorizationDenied("only the author may edit this contribution")
        attempt_target = None
        if payload.attempt is not None:
            from polycolab.research.attempts import validate_structure as validate_attempt

            attempt_target = validate_attempt(
                session,
                project_id=payload.project_id,
                payload=payload.attempt,
                existing_attempt_object=obj,
            )
        if isinstance(payload, SnapshotRecordWrite):
            attached = payload.semantic_metadata.get("attached_object_ids", [])
            assert isinstance(attached, list)
            for attached_id in attached:
                parent = session.get(SqlResearchObject, UUID(str(attached_id)))
                if (
                    parent is None
                    or parent.current_revision_id is None
                    or parent.id == payload.object_id
                ):
                    raise ResearchNotFound
                accessible_revision(session, parent.current_revision_id, payload.project_id)
        for target_id in payload.statement_revision_ids:
            accessible_revision(session, target_id, payload.project_id)
            if (
                payload.kind.value != "FORMALIZATION"
                and session.get(SqlStatementRevision, target_id) is None
            ):
                raise DomainConflict("attachment target must be a statement")
        existing = mutation_keys.receipt(session, actor_key, "record.write", key, body)
        if existing is not None:
            result = ResourceResult(
                id=UUID(existing.resource_ids[0]), revision_id=UUID(existing.resource_ids[1])
            )
            if commit:
                session.commit()
            return result
        if obj is not None and (
            obj.current_revision_id != payload.base_revision_id
            or canonical_kind(obj.kind) != canonical_kind(payload.kind)
        ):
            raise DomainConflict("stale revision or changed kind")
        envelope = contribution or human_contribution(
            session, user_id=user_id, scope_id=scope.id, operation="record.write"
        )
        provenance = _provenance_kind(envelope)
        initial = obj is None
        if obj is None:
            obj = SqlResearchObject(
                ownership_scope_id=scope.id,
                kind=payload.kind,
                entity_class=KIND_DEFINITIONS[payload.kind].entity_class,
                contribution_id=envelope.id,
                created_by_user_id=user_id,
                provenance_kind=provenance,
            )
            session.add(obj)
            session.flush()
        base = (
            session.get(SqlObjectRevision, obj.current_revision_id)
            if obj.current_revision_id
            else None
        )
        revision = SqlObjectRevision(
            object_id=obj.id,
            ownership_scope_id=scope.id,
            number=base.number + 1 if base else 1,
            base_revision_id=base.id if base else None,
            title=payload.title,
            content_md=payload.content_md,
            semantic_metadata=payload.semantic_metadata
            if isinstance(payload, SnapshotRecordWrite)
            else {},
            rationale=payload.change_summary
            if isinstance(payload, SnapshotRecordWrite)
            else payload.reason,
            contribution_id=envelope.id,
            created_by_user_id=user_id,
            provenance_kind=provenance,
        )
        session.add(revision)
        session.flush()
        if obj.entity_class == ResearchEntityClass.STATEMENT:
            session.add(
                SqlStatementRevision(
                    revision_id=revision.id,
                    kind=obj.kind.value,
                    assumptions_md=payload.assumptions_md,
                    reported_outcome=payload.reported_outcome,
                    explanation_md=payload.explanation_md,
                )
            )
        else:
            session.add(
                SqlRecordRevision(
                    revision_id=revision.id,
                    kind=obj.kind.value,
                    assumptions_md=payload.assumptions_md,
                    reported_outcome=payload.reported_outcome,
                    explanation_md=payload.explanation_md,
                )
            )
        session.flush()
        if payload.proof_sketch is not None:
            from polycolab.research.proofs import add_structure

            add_structure(
                session,
                revision_id=revision.id,
                payload=payload.proof_sketch,
                positions=payload.premise_positions
                if isinstance(payload, SnapshotRecordWrite)
                else None,
            )
        if payload.attempt is not None:
            from polycolab.research.attempts import add_structure as add_attempt

            assert attempt_target is not None
            add_attempt(
                session,
                revision_id=revision.id,
                target=attempt_target,
                payload=payload.attempt,
                positions=payload.evidence_positions
                if isinstance(payload, SnapshotRecordWrite)
                else None,
            )
        for target_id in payload.statement_revision_ids:
            add_structural_relationship(
                session,
                source_object_version_id=revision.id,
                target_object_version_id=target_id,
                relationship_type=StructuralRole.ATTACHMENT,
            )
        if payload.suggestion is not None:
            target = public_revision(session, payload.suggestion.base_revision_id)
            if session.get(SqlCatalogueEntry, target.object_id) is None:
                raise DomainConflict("correction target must be an admitted statement")
            session.add(
                SqlCorrectionSuggestion(
                    revision_id=revision.id,
                    target_revision_id=target.id,
                    proposed=payload.suggestion.model_dump(mode="json"),
                )
            )
        obj.current_revision_id = revision.id
        link_output(
            session,
            envelope=envelope,
            entity_type=CanonicalEntityType.OBJECT_REVISION,
            entity_id=revision.id,
            scope_id=scope.id,
        )
        if initial:
            link_output(
                session,
                envelope=envelope,
                entity_type=CanonicalEntityType.RESEARCH_OBJECT,
                entity_id=obj.id,
                scope_id=scope.id,
            )
        if payload.project_id is None:
            anchors: set[UUID] = set()
            for target_id in payload.statement_revision_ids:
                anchors.update(
                    session.scalars(
                        select(SqlCatalogueRevision.entry_id).where(
                            SqlCatalogueRevision.revision_id == target_id
                        )
                    )
                )
                anchors.update(
                    session.scalars(
                        select(SqlPublicResearchAnchor.entry_id).where(
                            SqlPublicResearchAnchor.revision_id == target_id
                        )
                    )
                )
            if not anchors:
                raise DomainConflict("public contributions require admitted ancestry")
            for entry_id in anchors:
                session.add(SqlPublicResearchAnchor(revision_id=revision.id, entry_id=entry_id))
            session.flush()
            fields = record_read(session, revision, payload.project_id).model_dump(
                mode="json", exclude_computed_fields=True
            )
            session.add(
                SqlPublicRelease(
                    object_revision_id=revision.id,
                    ownership_scope_id=scope.id,
                    contribution_id=envelope.id,
                    projection_version=4,
                    public_fields=fields,
                    public_fields_digest=canonical_digest(fields),
                )
            )
        mutation_keys.save(session, actor_key, "record.write", key, body, [obj.id, revision.id])
        session.flush()
        result = ResourceResult(id=obj.id, revision_id=revision.id)
        if commit:
            session.commit()
        return result
    except Exception:
        session.rollback()
        raise


def write_relation(
    session: Session,
    *,
    actor: Actor,
    payload: ScopedRelationWrite,
    key: str,
    contribution: SqlContributionEnvelope | None = None,
    commit: bool = True,
) -> ResourceResult:
    from polycolab.research.contracts import SnapshotRelationWrite

    if actor.kind == ActorKind.AGENT:
        if (
            contribution is None
            or ActorOperation.CONTRIBUTION_CREATE not in actor.operation_scope
            or contribution.run_id != actor.run_id
        ):
            raise AuthorizationDenied("missing validated relation authority")
    else:
        require_human_actor(actor, action="research relation")
    user_id = actor.human_user_id if actor.kind == ActorKind.HUMAN else actor.sponsor_user_id
    assert user_id is not None
    actor_key = (
        f"human:{user_id}"
        if actor.kind == ActorKind.HUMAN
        else f"agent:{actor.external_agent_id or actor.external_run_id or actor.run_id}"
    )
    body = payload.model_dump(mode="json")
    try:
        mutation_keys.lock_key(session, actor_key, "relation.write", key)
        if payload.project_id is not None:
            project_access(session, payload.project_id, user_id, write=True)
        commons = lock_commons(session)
        source = accessible_revision(session, payload.source_revision_id, payload.project_id)
        symmetric = payload.relation_type is RelationType.EQUIVALENT_TO
        destination_scope_id = source.ownership_scope_id
        if symmetric:
            destination_scope_id = commons.id
            if payload.project_id is not None:
                destination_scope = session.scalar(
                    select(SqlResearchScope).where(
                        SqlResearchScope.project_id == payload.project_id
                    )
                )
                if destination_scope is None:
                    raise ResearchNotFound
                destination_scope_id = destination_scope.id
        if contribution is not None and contribution.ownership_scope_id != destination_scope_id:
            raise AuthorizationDenied("contribution destination mismatch")
        accessible_revision(session, payload.target_revision_id, payload.project_id)
        if (
            not symmetric
            and payload.project_id is not None
            and source.project_id != payload.project_id
        ):
            raise AuthorizationDenied("private relations must originate in their workspace")
        existing = mutation_keys.receipt(session, actor_key, "relation.write", key, body)
        if existing is not None:
            result = ResourceResult(id=UUID(existing.resource_ids[0]))
        else:
            envelope = contribution or human_contribution(
                session,
                user_id=user_id,
                scope_id=destination_scope_id,
                operation="relation.write",
            )
            relation = add_declaration(
                session,
                ownership_scope_id=destination_scope_id,
                source_revision_id=source.id,
                target_revision_id=payload.target_revision_id,
                relation_type=payload.relation_type,
                rationale=payload.description
                if isinstance(payload, SnapshotRelationWrite)
                else payload.rationale,
                contribution_id=envelope.id,
                created_by_user_id=user_id,
                provenance_kind=_provenance_kind(envelope),
            )
            link_output(
                session,
                envelope=envelope,
                entity_type=CanonicalEntityType.RELATION_ASSERTION,
                entity_id=relation.id,
                scope_id=destination_scope_id,
            )
            mutation_keys.save(session, actor_key, "relation.write", key, body, [relation.id])
            result = ResourceResult(id=relation.id)
        if commit:
            session.commit()
        return result
    except Exception:
        session.rollback()
        raise
