"""Transactional operations for immutable project research state."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor, ActorKind, human_actor
from polycolab.access.authorization import (
    AuthorizationDenied,
    WorkspaceAction,
    require_human_actor,
    require_workspace_write,
    workspace_policy,
)
from polycolab.db.models import (
    SqlContributionEnvelope,
    SqlObjectRevision,
    SqlRecordRevision,
    SqlRelationAssertion,
    SqlResearchAttachment,
    SqlResearchComment,
    SqlResearchObject,
    SqlResearchScope,
    SqlStatementRevision,
    SqlUser,
)
from polycolab.db.stores.relationships import add_declaration, add_structural_relationship
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.accounts import IdentifiedUser
from polycolab.entities.enums import (
    CanonicalEntityType,
    ProvenanceKind,
    RelationType,
    ResearchEntityClass,
    ResearchObjectKind,
    ResearchScopeKind,
)
from polycolab.entities.research import KIND_DEFINITIONS, StructuralRole
from polycolab.research.contributions import human_contribution, link_output
from polycolab.research.schemas import ProofStructureRequest, ResearchAttemptRequest
from polycolab.workspaces.service import DomainConflict


class ResearchNotFound(Exception):
    """Deliberately used for unknown and inaccessible project research."""


class StaleRevision(DomainConflict):
    pass


def _authorize_write(
    session: Session, project_id: UUID, author: IdentifiedUser, actor: Actor | None
) -> None:
    actor = actor or human_actor(author.id)
    if actor.kind is ActorKind.HUMAN:
        if actor.human_user_id != author.id:
            raise AuthorizationDenied
    else:
        require_workspace_write(actor, project_id=project_id)
        if actor.sponsor_user_id != author.id:
            raise AuthorizationDenied
    workspace_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, author.id, WorkspaceAction.CREATE_RESEARCH
    )


def _commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise DomainConflict from error


def _workspace_scope_id(session: Session, project_id: UUID) -> UUID:
    scope_id = session.scalar(
        select(SqlResearchScope.id).where(
            SqlResearchScope.project_id == project_id,
            SqlResearchScope.scope_kind == ResearchScopeKind.WORKSPACE,
        )
    )
    if scope_id is None:
        raise ResearchNotFound
    return scope_id


def _lock_graph_scope(session: Session) -> None:
    """Serialize cross-scope proof writes when the canonical commons exists.

    Production baselines always contain it. Lightweight SQLite unit databases
    built from ORM metadata may exercise private M0 routes without bootstrapping
    catalogue state.
    """

    from polycolab.catalogue.admission import lock_commons

    exists = session.scalar(
        select(SqlResearchScope.id).where(SqlResearchScope.scope_kind == ResearchScopeKind.COMMONS)
    )
    if exists is not None:
        lock_commons(session)


def object_in_project(session: Session, *, project_id: UUID, object_id: UUID) -> SqlResearchObject:
    research_object = session.scalar(
        select(SqlResearchObject).where(
            SqlResearchObject.id == object_id, SqlResearchObject.project_id == project_id
        )
    )
    if research_object is None:
        raise ResearchNotFound
    return research_object


def object_by_id(session: Session, *, object_id: UUID) -> SqlResearchObject:
    research_object = session.get(SqlResearchObject, object_id)
    if research_object is None:
        raise ResearchNotFound
    return research_object


def revision_in_project(
    session: Session, *, project_id: UUID, revision_id: UUID, object_id: UUID | None = None
) -> SqlObjectRevision:
    statement = (
        select(SqlObjectRevision)
        .join(SqlResearchObject, SqlObjectRevision.object_id == SqlResearchObject.id)
        .where(SqlResearchObject.project_id == project_id, SqlObjectRevision.id == revision_id)
    )
    if object_id is not None:
        statement = statement.where(SqlObjectRevision.object_id == object_id)
    revision = session.scalar(statement)
    if revision is None:
        raise ResearchNotFound
    return revision


def create_object(
    session: Session,
    *,
    project_id: UUID | None = None,
    ownership_scope_id: UUID | None = None,
    kind: ResearchObjectKind,
    title: str,
    content_md: str,
    rationale: str | None,
    author: IdentifiedUser,
    provenance_kind: ProvenanceKind = ProvenanceKind.HUMAN_DIRECT,
    commit: bool = True,
    actor: Actor | None = None,
    contribution: SqlContributionEnvelope | None = None,
    assumptions_md: str = "",
    proof: ProofStructureRequest | None = None,
    attempt: ResearchAttemptRequest | None = None,
) -> tuple[SqlResearchObject, SqlObjectRevision]:
    if kind is ResearchObjectKind.PROOF:
        raise DomainConflict("new proof approaches must use PROOF_SKETCH")
    if project_id is not None:
        _authorize_write(session, project_id, author, actor)
        workspace_scope = _workspace_scope_id(session, project_id)
        if ownership_scope_id is not None and ownership_scope_id != workspace_scope:
            raise ResearchNotFound
        ownership_scope_id = workspace_scope
    else:
        trusted_actor = actor or human_actor(author.id)
        require_human_actor(trusted_actor, action="commons research creation")
        if trusted_actor.human_user_id != author.id:
            raise AuthorizationDenied
        scope = session.scalar(
            select(SqlResearchScope)
            .where(
                SqlResearchScope.id == ownership_scope_id,
                SqlResearchScope.scope_kind == ResearchScopeKind.COMMONS,
            )
            .with_for_update()
        )
        if scope is None or session.get(SqlUser, author.id) is None:
            raise ResearchNotFound
        ownership_scope_id = scope.id
    assert ownership_scope_id is not None
    from polycolab.research.attempts import require_structure as require_attempt
    from polycolab.research.proofs import require_structure, validate_structure

    require_structure(kind, proof)
    require_attempt(kind, attempt)
    if proof is not None:
        _lock_graph_scope(session)
        validate_structure(session, project_id=project_id, kind=kind, payload=proof)
    attempt_target = None
    if attempt is not None:
        from polycolab.research.attempts import validate_structure as validate_attempt

        attempt_target = validate_attempt(session, project_id=project_id, payload=attempt)
    contribution = contribution or human_contribution(
        session, user_id=author.id, scope_id=ownership_scope_id, operation="CREATE_OBJECT"
    )
    research_object = SqlResearchObject(
        contribution_id=contribution.id,
        entity_class=KIND_DEFINITIONS[kind].entity_class,
        ownership_scope_id=ownership_scope_id,
        kind=kind,
        created_by_user_id=author.id,
        provenance_kind=provenance_kind,
    )
    session.add(research_object)
    try:
        session.flush()
        revision = SqlObjectRevision(
            contribution_id=contribution.id,
            object_id=research_object.id,
            ownership_scope_id=ownership_scope_id,
            number=1,
            title=title,
            content_md=content_md,
            rationale=rationale,
            base_revision_id=None,
            created_by_user_id=author.id,
            provenance_kind=provenance_kind,
        )
        session.add(revision)
        session.flush()
        add_revision_metadata(session, research_object, revision, assumptions_md=assumptions_md)
        if proof is not None:
            from polycolab.research.proofs import add_structure

            add_structure(session, revision_id=revision.id, payload=proof)
            for statement_id in dict.fromkeys(
                [proof.conclusion_revision_id, *proof.premise_revision_ids]
            ):
                add_structural_relationship(
                    session,
                    source_object_version_id=revision.id,
                    target_object_version_id=statement_id,
                    relationship_type=StructuralRole.ATTACHMENT,
                )
        if attempt is not None:
            from polycolab.research.attempts import add_structure as add_attempt

            assert attempt_target is not None
            add_attempt(
                session,
                revision_id=revision.id,
                target=attempt_target,
                payload=attempt,
            )
        research_object.current_revision_id = revision.id
        link_output(
            session,
            envelope=contribution,
            entity_type=CanonicalEntityType.OBJECT_REVISION,
            entity_id=revision.id,
            scope_id=ownership_scope_id,
        )
        if revision.number == 1:
            link_output(
                session,
                envelope=contribution,
                entity_type=CanonicalEntityType.RESEARCH_OBJECT,
                entity_id=research_object.id,
                scope_id=ownership_scope_id,
            )
        if commit:
            _commit(session)
        else:
            session.flush()
    except Exception:
        session.rollback()
        raise
    if commit:
        session.refresh(research_object)
        session.refresh(revision)
    return research_object, revision


def create_revision(
    session: Session,
    *,
    project_id: UUID,
    object_id: UUID,
    base_revision_id: UUID,
    title: str,
    content_md: str,
    rationale: str | None,
    author: IdentifiedUser,
    provenance_kind: ProvenanceKind = ProvenanceKind.HUMAN_DIRECT,
    commit: bool = True,
    actor: Actor | None = None,
    contribution: SqlContributionEnvelope | None = None,
    proof: ProofStructureRequest | None = None,
    attempt: ResearchAttemptRequest | None = None,
) -> tuple[SqlResearchObject, SqlObjectRevision]:
    """Serialize appends on the stable object and reject a non-current base."""

    from polycolab.research.records import accessible_revision

    _authorize_write(session, project_id, author, actor)
    unlocked_object = object_in_project(session, project_id=project_id, object_id=object_id)
    from polycolab.research.attempts import require_structure as require_attempt
    from polycolab.research.proofs import require_structure, validate_structure

    require_structure(unlocked_object.kind, proof)
    require_attempt(unlocked_object.kind, attempt)
    targets = list(
        session.scalars(
            select(SqlResearchAttachment.statement_revision_id).where(
                SqlResearchAttachment.revision_id == base_revision_id
            )
        )
    )
    if proof is not None:
        targets = list(
            dict.fromkeys([*targets, proof.conclusion_revision_id, *proof.premise_revision_ids])
        )
    if targets:
        _lock_graph_scope(session)
    if proof is not None:
        validate_structure(session, project_id=project_id, kind=unlocked_object.kind, payload=proof)
    attempt_target = None
    if attempt is not None:
        from polycolab.research.attempts import validate_structure as validate_attempt

        attempt_target = validate_attempt(
            session,
            project_id=project_id,
            payload=attempt,
            existing_attempt_object=unlocked_object,
        )
    research_object = session.scalar(
        select(SqlResearchObject)
        .where(SqlResearchObject.id == object_id, SqlResearchObject.project_id == project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if research_object is None:
        raise ResearchNotFound
    if research_object.created_by_user_id != author.id:
        raise AuthorizationDenied("only the author may edit this contribution")
    if research_object.current_revision_id != base_revision_id:
        raise StaleRevision
    base = revision_in_project(
        session, project_id=project_id, revision_id=base_revision_id, object_id=object_id
    )
    ownership_scope_id = research_object.ownership_scope_id
    contribution = contribution or human_contribution(
        session, user_id=author.id, scope_id=ownership_scope_id, operation="CREATE_REVISION"
    )
    revision = SqlObjectRevision(
        contribution_id=contribution.id,
        object_id=research_object.id,
        ownership_scope_id=ownership_scope_id,
        number=base.number + 1,
        title=title,
        content_md=content_md,
        rationale=rationale,
        base_revision_id=base.id,
        created_by_user_id=author.id,
        provenance_kind=provenance_kind,
    )
    session.add(revision)
    try:
        session.flush()
        copy_revision_metadata(session, research_object, base, revision)
        if proof is not None:
            from polycolab.research.proofs import add_structure

            add_structure(session, revision_id=revision.id, payload=proof)
        if attempt is not None:
            from polycolab.research.attempts import add_structure as add_attempt

            assert attempt_target is not None
            add_attempt(
                session,
                revision_id=revision.id,
                target=attempt_target,
                payload=attempt,
            )
        for target_id in targets:
            accessible_revision(session, target_id, project_id)
            add_structural_relationship(
                session,
                source_object_version_id=revision.id,
                target_object_version_id=target_id,
                relationship_type=StructuralRole.ATTACHMENT,
            )
        research_object.current_revision_id = revision.id
        link_output(
            session,
            envelope=contribution,
            entity_type=CanonicalEntityType.OBJECT_REVISION,
            entity_id=revision.id,
            scope_id=ownership_scope_id,
        )
        if commit:
            _commit(session)
        else:
            session.flush()
    except IntegrityError as error:
        # A concurrent writer can win the row lock between the current-revision
        # check and the revision-number insert on PostgreSQL. Preserve the
        # optimistic-concurrency contract instead of leaking a 500 from the
        # append-only uniqueness constraint.
        session.rollback()
        raise StaleRevision from error
    except Exception:
        session.rollback()
        raise
    if commit:
        session.refresh(research_object)
        session.refresh(revision)
    return research_object, revision


def create_relation(
    session: Session,
    *,
    project_id: UUID,
    source_revision_id: UUID,
    target_revision_id: UUID,
    relation_type: RelationType,
    rationale: str,
    author: IdentifiedUser,
    provenance_kind: ProvenanceKind = ProvenanceKind.HUMAN_DIRECT,
    commit: bool = True,
    actor: Actor | None = None,
    contribution: SqlContributionEnvelope | None = None,
) -> SqlRelationAssertion:
    _authorize_write(session, project_id, author, actor)
    from polycolab.research.records import accessible_revision

    # The assertion itself belongs to the destination workspace. Its source must
    # therefore be destination-owned, while its exact target may be any public
    # revision. This permits public cross-workspace dependencies without granting
    # write authority in the target workspace.
    if relation_type is RelationType.EQUIVALENT_TO:
        accessible_revision(session, source_revision_id, project_id)
    else:
        revision_in_project(session, project_id=project_id, revision_id=source_revision_id)
    accessible_revision(session, target_revision_id, project_id)
    scope_id = _workspace_scope_id(session, project_id)
    contribution = contribution or human_contribution(
        session, user_id=author.id, scope_id=scope_id, operation="CREATE_RELATION_ASSERTION"
    )
    relation = add_declaration(
        session,
        contribution_id=contribution.id,
        ownership_scope_id=_workspace_scope_id(session, project_id),
        source_revision_id=source_revision_id,
        target_revision_id=target_revision_id,
        relation_type=relation_type,
        rationale=rationale,
        created_by_user_id=author.id,
        provenance_kind=provenance_kind,
    )
    link_output(
        session,
        envelope=contribution,
        entity_type=CanonicalEntityType.RELATION_ASSERTION,
        entity_id=relation.id,
        scope_id=scope_id,
    )
    if commit:
        _commit(session)
        session.refresh(relation)
    else:
        session.flush()
    return relation


def create_comment(
    session: Session,
    *,
    project_id: UUID,
    object_id: UUID,
    revision_id: UUID,
    body_md: str,
    author: IdentifiedUser,
    provenance_kind: ProvenanceKind = ProvenanceKind.HUMAN_DIRECT,
    commit: bool = True,
    actor: Actor | None = None,
    contribution: SqlContributionEnvelope | None = None,
) -> SqlResearchComment:
    _authorize_write(session, project_id, author, actor)
    revision_in_project(
        session, project_id=project_id, revision_id=revision_id, object_id=object_id
    )
    scope_id = _workspace_scope_id(session, project_id)
    contribution = contribution or human_contribution(
        session, user_id=author.id, scope_id=scope_id, operation="CREATE_RESEARCH_COMMENT"
    )
    comment = SqlResearchComment(
        contribution_id=contribution.id,
        ownership_scope_id=_workspace_scope_id(session, project_id),
        object_id=object_id,
        revision_id=revision_id,
        body_md=body_md,
        created_by_user_id=author.id,
        provenance_kind=provenance_kind,
    )
    session.add(comment)
    session.flush()
    link_output(
        session,
        envelope=contribution,
        entity_type=CanonicalEntityType.RESEARCH_COMMENT,
        entity_id=comment.id,
        scope_id=scope_id,
    )
    if commit:
        _commit(session)
        session.refresh(comment)
    else:
        session.flush()
    return comment


def revisions_for_object(session: Session, *, object_id: UUID) -> list[SqlObjectRevision]:
    return list(
        session.scalars(
            select(SqlObjectRevision)
            .where(SqlObjectRevision.object_id == object_id)
            .order_by(SqlObjectRevision.number.desc(), SqlObjectRevision.id.desc())
        )
    )


def relations_for_object(session: Session, *, object_id: UUID) -> list[SqlRelationAssertion]:
    from polycolab.research.records import relation_read_condition

    obj = session.get(SqlResearchObject, object_id)
    if obj is None:
        raise ResearchNotFound
    revision_ids = select(SqlObjectRevision.id).where(SqlObjectRevision.object_id == object_id)
    return list(
        session.scalars(
            select(SqlRelationAssertion)
            .where(
                relation_read_condition(obj.project_id),
                or_(
                    SqlRelationAssertion.source_revision_id.in_(revision_ids),
                    SqlRelationAssertion.target_revision_id.in_(revision_ids),
                ),
            )
            .order_by(SqlRelationAssertion.created_at, SqlRelationAssertion.id)
        )
    )


def comments_for_object(session: Session, *, object_id: UUID) -> list[SqlResearchComment]:
    return list(
        session.scalars(
            select(SqlResearchComment)
            .where(SqlResearchComment.object_id == object_id)
            .order_by(SqlResearchComment.created_at, SqlResearchComment.id)
        )
    )


def neighborhood(
    session: Session, *, project_id: UUID, revision_id: UUID
) -> list[SqlRelationAssertion]:
    revision_in_project(session, project_id=project_id, revision_id=revision_id)
    return list(
        session.scalars(
            select(SqlRelationAssertion)
            .where(
                SqlRelationAssertion.project_id == project_id,
                or_(
                    SqlRelationAssertion.source_revision_id == revision_id,
                    SqlRelationAssertion.target_revision_id == revision_id,
                ),
            )
            .order_by(SqlRelationAssertion.created_at, SqlRelationAssertion.id)
        )
    )


def dependents(
    session: Session, *, project_id: UUID, revision_id: UUID
) -> list[SqlRelationAssertion]:
    from polycolab.research.records import relation_read_condition

    revision_in_project(session, project_id=project_id, revision_id=revision_id)
    return list(
        session.scalars(
            select(SqlRelationAssertion)
            .where(
                SqlRelationAssertion.project_id == project_id,
                relation_read_condition(project_id),
                SqlRelationAssertion.relation_type != RelationType.EQUIVALENT_TO,
                SqlRelationAssertion.target_revision_id == revision_id,
            )
            .order_by(SqlRelationAssertion.created_at, SqlRelationAssertion.id)
        )
    )


def copy_revision_metadata(
    session: Session,
    research_object: SqlResearchObject,
    base: SqlObjectRevision,
    revision: SqlObjectRevision,
) -> None:
    """Content-only edits preserve declared metadata, not independent assurance."""
    metadata_type = (
        SqlStatementRevision
        if research_object.entity_class is ResearchEntityClass.STATEMENT
        else SqlRecordRevision
    )
    metadata = cast(
        SqlStatementRevision | SqlRecordRevision | None, session.get(metadata_type, base.id)
    )
    assert metadata is not None
    session.add(
        metadata_type(
            revision_id=revision.id,
            kind=metadata.kind,
            assumptions_md=metadata.assumptions_md,
            reported_outcome=metadata.reported_outcome,
            explanation_md=metadata.explanation_md,
        )
    )
    session.flush()


def add_revision_metadata(
    session: Session,
    research_object: SqlResearchObject,
    revision: SqlObjectRevision,
    *,
    assumptions_md: str = "",
) -> None:
    if research_object.entity_class is ResearchEntityClass.STATEMENT:
        session.add(
            SqlStatementRevision(
                revision_id=revision.id,
                kind=research_object.kind.value,
                assumptions_md=assumptions_md,
            )
        )
    else:
        session.add(SqlRecordRevision(revision_id=revision.id, kind=research_object.kind.value))
    session.flush()
