"""Version-pinned review policy shared by humans and scoped agents."""

from uuid import UUID

from sqlalchemy import Integer, Select, and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from polycolab.access.actors import Actor, ActorKind, ActorOperation
from polycolab.access.authorization import AuthorizationDenied
from polycolab.db.models import (
    SqlAgentRun,
    SqlContributionEnvelope,
    SqlExternalAgentIdentity,
    SqlObjectRevision,
    SqlPlatformAgentVersion,
    SqlProject,
    SqlResearchScope,
    SqlUser,
)
from polycolab.db.models.reviews import SqlObjectReview, SqlPublicationReview, SqlReviewEvidence
from polycolab.platform import mutation_keys
from polycolab.research.objects import ResearchNotFound
from polycolab.research.records import accessible_revision, read_condition
from polycolab.research.review_schemas import ReviewCounts, ReviewRead, ReviewSummary, ReviewWrite


def read(row: SqlObjectReview) -> ReviewRead:
    return ReviewRead.model_validate(row, from_attributes=True)


def write(
    session: Session,
    *,
    actor: Actor,
    payload: ReviewWrite,
    contribution: SqlContributionEnvelope,
    key: str | None = None,
) -> ReviewRead:
    if (
        actor.kind == ActorKind.AGENT
        and ActorOperation.REVIEW_RESEARCH not in actor.operation_scope
    ):
        raise AuthorizationDenied("review capability required")
    scope = session.get(SqlResearchScope, contribution.ownership_scope_id)
    if scope is None:
        raise ResearchNotFound
    revision = accessible_revision(session, payload.object_version_id, scope.project_id)
    # Serialize assessments against the target, including concurrent withdrawal.
    session.execute(
        select(SqlObjectRevision.id).where(SqlObjectRevision.id == revision.id).with_for_update()
    )
    for evidence_id in payload.evidence_object_version_ids:
        accessible_revision(session, evidence_id, scope.project_id)
    if actor.kind == ActorKind.HUMAN:
        reviewer_id = f"human:{actor.human_user_id}"
        user = session.get(SqlUser, actor.human_user_id)
        name = user.display_name if user else None
        original = session.get(SqlContributionEnvelope, revision.contribution_id)
        own = original is not None and original.human_user_id == actor.human_user_id
    else:
        identity = actor.external_agent_id or actor.agent_version_id
        reviewer_id = f"agent:{identity}"
        if actor.external_agent_id:
            agent = session.get(SqlExternalAgentIdentity, actor.external_agent_id)
            name = agent.name if agent else None
        else:
            hosted = session.get(SqlPlatformAgentVersion, actor.agent_version_id)
            name = hosted.display_name if hosted else None
        original = session.get(SqlContributionEnvelope, revision.contribution_id)
        own = original is not None and (
            (
                actor.external_agent_id is not None
                and original.external_agent_id == actor.external_agent_id
            )
            or (
                actor.agent_version_id is not None
                and original.agent_version_id == actor.agent_version_id
            )
        )
    if not name:
        name = "Researcher" if actor.kind == ActorKind.HUMAN else "Agent"
    receipt_actor = f"agent:{actor.run_id}" if actor.run_id else reviewer_id
    body = payload.model_dump(mode="json")
    if key:
        mutation_keys.lock_key(session, receipt_actor, "research.review", key)
        receipt = mutation_keys.receipt(session, receipt_actor, "research.review", key, body)
        if receipt:
            previous = session.get(SqlObjectReview, UUID(receipt.resource_ids[0]))
            if previous is None:
                raise ResearchNotFound
            return read(previous)
    run = session.get(SqlAgentRun, actor.run_id) if actor.run_id else None
    row = SqlObjectReview(
        model_id=run.gateway_model_id if run else None,
        object_version_id=revision.id,
        ownership_scope_id=scope.id,
        contribution_id=contribution.id,
        reviewer_id=reviewer_id,
        actor_kind=actor.kind.value,
        reviewer_name=name,
        outcome=payload.outcome,
        scope=payload.scope,
        rationale=payload.rationale,
        evidence_object_version_ids=[str(value) for value in payload.evidence_object_version_ids],
        withdrawn=payload.withdrawn,
        self_review=own,
    )
    session.add(row)
    session.flush()
    for evidence_id in payload.evidence_object_version_ids:
        session.add(SqlReviewEvidence(review_id=row.id, object_version_id=evidence_id))
    session.flush()
    if key:
        mutation_keys.save(session, receipt_actor, "research.review", key, body, [row.id])
    return read(row)


def visible_condition(workspace_id: UUID | None) -> ColumnElement[bool]:
    """Private review scopes are never exposed just because the target is public."""
    public_scope: ColumnElement[bool] = exists(
        select(SqlResearchScope.id).where(
            SqlResearchScope.id == SqlObjectReview.ownership_scope_id,
            or_(
                SqlResearchScope.project_id.is_(None),
                exists(
                    select(SqlProject.id).where(
                        SqlProject.id == SqlResearchScope.project_id,
                        SqlProject.visibility == "PUBLIC",
                    )
                ),
            ),
        )
    )
    authorized_evidence = ~exists(
        select(SqlReviewEvidence.review_id).where(
            SqlReviewEvidence.review_id == SqlObjectReview.id,
            SqlReviewEvidence.object_version_id.not_in(
                select(SqlObjectRevision.id).where(read_condition(workspace_id))
            ),
        )
    )
    public_scope = or_(
        public_scope,
        exists(
            select(SqlPublicationReview.review_id).where(
                SqlPublicationReview.review_id == SqlObjectReview.id
            )
        ),
    )
    if workspace_id is None:
        return and_(public_scope, authorized_evidence)
    return and_(
        authorized_evidence,
        or_(
            public_scope,
            exists(
                select(SqlResearchScope.id).where(
                    SqlResearchScope.id == SqlObjectReview.ownership_scope_id,
                    SqlResearchScope.project_id == workspace_id,
                )
            ),
        ),
    )


def current_query(
    version_ids: list[UUID], workspace_id: UUID | None
) -> Select[tuple[SqlObjectReview]]:
    later = aliased(SqlObjectReview)
    visible = visible_condition(workspace_id)
    # Latest among authorized positions; a private review must not suppress a public one.
    visible_ids = select(SqlObjectReview.id).where(visible).correlate(None)
    return select(SqlObjectReview).where(
        SqlObjectReview.object_version_id.in_(version_ids),
        visible,
        ~exists(
            select(later.id).where(
                later.id.in_(visible_ids),
                later.object_version_id == SqlObjectReview.object_version_id,
                later.reviewer_id == SqlObjectReview.reviewer_id,
                or_(
                    later.created_at > SqlObjectReview.created_at,
                    and_(
                        later.created_at == SqlObjectReview.created_at,
                        later.id > SqlObjectReview.id,
                    ),
                ),
            )
        ),
    )


def summaries(
    session: Session, version_ids: list[UUID], workspace_id: UUID | None
) -> list[ReviewSummary]:
    result = {
        key: ReviewSummary(object_version_id=key, human=ReviewCounts(), ai=ReviewCounts())
        for key in version_ids
    }
    current = current_query(version_ids, workspace_id).subquery()
    for version_id, actor_kind, outcome, count, self_count in session.execute(
        select(
            current.c.object_version_id,
            current.c.actor_kind,
            current.c.outcome,
            func.count(),
            func.sum(current.c.self_review.cast(Integer)),
        )
        .where(current.c.withdrawn.is_(False))
        .group_by(current.c.object_version_id, current.c.actor_kind, current.c.outcome)
    ):
        counts = result[version_id].human if actor_kind == "HUMAN" else result[version_id].ai
        field = {
            "REVIEWED": "reviewed",
            "SUPPORTS": "supports",
            "ISSUES_FOUND": "issues_found",
            "INCONCLUSIVE": "inconclusive",
        }[outcome]
        setattr(counts, field, count)
        counts.self_reviews += self_count or 0
    return list(result.values())
