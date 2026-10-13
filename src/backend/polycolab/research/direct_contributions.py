"""Lease-fenced, attributable hosted mutations composed with human domain services."""

from datetime import UTC
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from polycolab.access.actors import ActorOperation, agent_actor
from polycolab.access.authorization import AuthorizationDenied
from polycolab.agents import grants as run_grants
from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentRunEvent,
    SqlContextManifest,
    SqlContributionEnvelope,
    SqlObjectRevision,
    SqlResearchObject,
    SqlResearchScope,
    SqlResearchSummary,
    SqlResearchSummaryRevision,
    SqlRunRevisionOutput,
    SqlRunToolCapability,
)
from polycolab.entities.enums import AgentRunEventKind, AgentRunStatus, ContributionActorKind
from polycolab.entities.time import utc_now
from polycolab.platform import mutation_keys
from polycolab.research import activity as research_activity
from polycolab.research import records, reviews
from polycolab.research.contracts import (
    RecordWrite,
    ResearchCommentRead,
    ResearchCommentToolWrite,
    ResearchProgressRead,
    ResearchProgressToolWrite,
    ResearchSummaryRead,
    ResearchSummaryToolWrite,
    ResourceResult,
    ScopedRelationWrite,
    SnapshotRecordWrite,
)
from polycolab.research.review_schemas import AgentReviewWrite, ReviewRead

DirectWrite = (
    RecordWrite
    | ScopedRelationWrite
    | ResearchSummaryToolWrite
    | ResearchCommentToolWrite
    | ResearchProgressToolWrite
    | AgentReviewWrite
)


def fence(session: Session, run: SqlAgentRun, capability: SqlRunToolCapability) -> None:
    if (
        run.status != AgentRunStatus.RUNNING
        or run.lease_expires_at is None
        or run.lease_expires_at.replace(tzinfo=UTC) <= utc_now()
        or capability.expires_at.replace(tzinfo=UTC) <= utc_now()
        or capability.revoked
        or run.lease_generation != capability.lease_generation
    ):
        session.rollback()
        raise AuthorizationDenied("lease expired before commit")


def mutate(
    session: Session,
    *,
    run: SqlAgentRun,
    capability: SqlRunToolCapability,
    manifest: SqlContextManifest,
    name: str,
    payload: DirectWrite,
    invocation: str,
    source_cursor: int,
) -> dict[str, object]:
    authority = run_grants.requested(session, run.id)
    if authority is None:
        raise AuthorizationDenied("missing run grant")
    run_grants.validate(
        session,
        project_id=run.project_id,
        user_id=run.requested_by_user_id,
        agent_version_id=run.agent_version_id,
        context_ids=[UUID(value) for value in manifest.revision_ids],
        authority=authority,
    )
    if isinstance(payload, ScopedRelationWrite):
        operation = "CREATE_RELATION"
    elif isinstance(payload, RecordWrite):
        operation = "REVISE_RECORD" if payload.object_id else "CREATE_RECORD"
    elif isinstance(payload, ResearchSummaryToolWrite):
        operation = "WRITE_SUMMARY"
    elif isinstance(payload, AgentReviewWrite):
        operation = "REVIEW_RESEARCH"
    elif isinstance(payload, ResearchCommentToolWrite):
        operation = "COMMENT"
    else:
        operation = "REPORT_PROGRESS"
    if operation not in authority.allowed_operations:
        raise AuthorizationDenied("operation not granted; use a suggestion")
    destination = run.project_id if authority.destination == "PROJECT" else None
    if payload.project_id != destination:
        raise AuthorizationDenied("destination not granted")
    readable = {UUID(value) for value in manifest.revision_ids}
    outputs = set(
        session.scalars(
            select(SqlRunRevisionOutput.revision_id).where(SqlRunRevisionOutput.run_id == run.id)
        )
    )
    readable.update(outputs)
    if isinstance(payload, RecordWrite):
        if payload.object_id is not None and payload.object_id not in authority.editable_object_ids:
            raise AuthorizationDenied("edit not granted; use a suggestion")
        targets = set(payload.statement_revision_ids)
        if isinstance(payload, SnapshotRecordWrite):
            attached = payload.semantic_metadata.get("attached_object_ids", [])
            if isinstance(attached, list):
                for object_id in attached:
                    parent = session.get(SqlResearchObject, UUID(str(object_id)))
                    if parent is None or parent.current_revision_id is None:
                        raise AuthorizationDenied("attachment target missing")
                    targets.add(parent.current_revision_id)
        if authority.destination == "PUBLIC" and not targets <= set(
            authority.public_target_revision_ids
        ):
            raise AuthorizationDenied("public attachment target not granted")
        if payload.base_revision_id is not None:
            targets.add(payload.base_revision_id)
        if payload.attempt is not None:
            targets.add(payload.attempt.target_revision_id)
            targets.update(item.revision_id for item in payload.attempt.evidence)
            if payload.attempt.result_revision_id is not None:
                targets.add(payload.attempt.result_revision_id)
        receipt_operation = "record.write"
    elif isinstance(payload, ScopedRelationWrite):
        targets = {payload.source_revision_id, payload.target_revision_id}
        if authority.destination == "PUBLIC" and payload.source_revision_id not in (
            set(authority.public_target_revision_ids) | outputs
        ):
            raise AuthorizationDenied("public relation source not granted")
        receipt_operation = "relation.write"
    elif isinstance(payload, ResearchSummaryToolWrite):
        targets = set(payload.source_revision_ids)
        receipt_operation = "research.summary"
    elif isinstance(payload, AgentReviewWrite):
        targets = {payload.object_version_id, *payload.evidence_object_version_ids}
        receipt_operation = "research.review"
    else:
        targets = {payload.revision_id}
        receipt_operation = (
            "research.comment"
            if isinstance(payload, ResearchCommentToolWrite)
            else "research.progress"
        )
    if not isinstance(payload, (RecordWrite, ScopedRelationWrite)):
        parent = session.get(SqlResearchObject, payload.object_id)
        if parent is None or not session.scalar(
            select(SqlObjectRevision.id).where(
                SqlObjectRevision.object_id == parent.id,
                SqlObjectRevision.id.in_(readable),
            )
        ):
            raise AuthorizationDenied("associated write target is not pinned")
    if authority.destination == "PUBLIC" and not targets <= (
        set(authority.public_target_revision_ids) | outputs
    ):
        raise AuthorizationDenied("public write target not granted")
    if not targets <= readable:
        raise AuthorizationDenied("write references unpinned inputs")
    for revision_id in targets:
        records.accessible_revision(session, revision_id, destination)
    if len(payload.model_dump_json().encode()) > authority.max_content_bytes:
        raise AuthorizationDenied("mutation byte budget exceeded")
    event = session.scalar(
        select(SqlAgentRunEvent).where(
            SqlAgentRunEvent.run_id == run.id,
            SqlAgentRunEvent.cursor == source_cursor,
        )
    )
    if (
        event is None
        or event.kind != AgentRunEventKind.TOOL_REQUESTED
        or event.payload.get("tool_name") != name
        or event.idempotency_key != f"{invocation}-requested"
    ):
        raise AuthorizationDenied("untrusted invocation provenance")
    actor_key = f"agent:{run.id}"
    body = payload.model_dump(mode="json")
    existing = mutation_keys.receipt(session, actor_key, receipt_operation, invocation, body)
    if isinstance(payload, ResearchSummaryToolWrite):
        summary = session.get(SqlResearchSummary, payload.object_id)
        if existing is not None:
            saved_summary = session.get(SqlResearchSummaryRevision, UUID(existing.resource_ids[0]))
            if saved_summary is None or summary is None:
                raise AuthorizationDenied("summary receipt target missing")
            if (
                saved_summary.base_revision_id is not None
                and payload.object_id not in authority.editable_object_ids
            ):
                raise AuthorizationDenied("summary edit not granted")
            replay_summary = research_activity._summary_read(
                session, summary, saved_summary, destination
            )
            fence(session, run, capability)
            session.commit()
            return replay_summary.model_dump(mode="json")
        if summary is not None and payload.object_id not in authority.editable_object_ids:
            raise AuthorizationDenied("summary edit not granted")
    if existing is not None and isinstance(payload, (RecordWrite, ScopedRelationWrite)):
        replay_result = ResourceResult(
            id=UUID(existing.resource_ids[0]),
            revision_id=UUID(existing.resource_ids[1]) if len(existing.resource_ids) > 1 else None,
        )
        fence(session, run, capability)
        session.commit()
        return replay_result.model_dump(mode="json")
    if existing is not None and isinstance(payload, AgentReviewWrite):
        from polycolab.db.models.reviews import SqlObjectReview

        saved_review = session.get(SqlObjectReview, UUID(existing.resource_ids[0]))
        if saved_review is None:
            raise AuthorizationDenied("review receipt target missing")
        fence(session, run, capability)
        session.commit()
        return reviews.read(saved_review).model_dump(mode="json")
    count = (
        session.scalar(
            select(func.count())
            .select_from(SqlContributionEnvelope)
            .where(
                SqlContributionEnvelope.run_id == run.id,
                SqlContributionEnvelope.operation.like("direct.%"),
            )
        )
        or 0
    )
    if count >= authority.max_mutations:
        raise AuthorizationDenied("run mutation budget exhausted")
    scope = session.scalar(
        select(SqlResearchScope).where(
            SqlResearchScope.project_id == destination
            if destination
            else SqlResearchScope.scope_kind == "COMMONS"
        )
    )
    assert scope is not None
    envelope = SqlContributionEnvelope(
        actor_kind=ContributionActorKind.AGENT,
        project_id=run.project_id,
        sponsor_user_id=run.requested_by_user_id,
        agent_version_id=run.agent_version_id,
        run_id=run.id,
        session_id=run.session_id,
        context_manifest_id=manifest.id,
        ownership_scope_id=scope.id,
        operation=f"direct.{receipt_operation}",
        source_event_cursors=[source_cursor],
    )
    session.add(envelope)
    session.flush()
    actor = agent_actor(
        sponsor_user_id=run.requested_by_user_id,
        agent_version_id=run.agent_version_id,
        run_id=run.id,
        capability_id=capability.id,
        session_id=run.session_id,
        context_manifest_id=manifest.id,
        project_id=run.project_id,
        ownership_scope_id=scope.id,
        operation_scope=frozenset(
            {
                ActorOperation.CONTRIBUTION_CREATE,
                ActorOperation.CONTRIBUTION_EDIT,
                *({ActorOperation.REVIEW_RESEARCH} if operation == "REVIEW_RESEARCH" else set()),
            }
        ),
    )
    result: (
        ResourceResult
        | ResearchSummaryRead
        | ResearchCommentRead
        | ResearchProgressRead
        | ReviewRead
    )
    if isinstance(payload, AgentReviewWrite):
        target = session.get(SqlObjectRevision, payload.object_version_id)
        if target is None or target.object_id != payload.object_id:
            raise AuthorizationDenied("review target does not belong to the object")
        result = reviews.write(
            session, actor=actor, payload=payload, contribution=envelope, key=invocation
        )
    elif isinstance(payload, RecordWrite):
        result = records.write_record(
            session,
            actor=actor,
            payload=payload,
            key=invocation,
            contribution=envelope,
            commit=False,
        )
        assert result.revision_id is not None
        session.add(
            SqlRunRevisionOutput(
                run_id=run.id, revision_id=result.revision_id, contribution_id=envelope.id
            )
        )
    elif isinstance(payload, ScopedRelationWrite):
        result = records.write_relation(
            session,
            actor=actor,
            payload=payload,
            key=invocation,
            contribution=envelope,
            commit=False,
        )
    elif isinstance(payload, ResearchSummaryToolWrite):
        result = research_activity.write_summary(
            session,
            actor=actor,
            object_id=payload.object_id,
            payload=payload,
            key=invocation,
            contribution=envelope,
            commit=False,
        )
    elif isinstance(payload, ResearchCommentToolWrite):
        result = research_activity.write_comment(
            session,
            actor=actor,
            object_id=payload.object_id,
            payload=payload,
            key=invocation,
            contribution=envelope,
            commit=False,
        )
    else:
        result = research_activity.write_progress(
            session,
            actor=actor,
            object_id=payload.object_id,
            payload=payload,
            key=invocation,
            contribution=envelope,
            commit=False,
        )
    session.flush()
    # The run row is held by the dispatcher throughout the transaction. Check
    # wall-clock expiry again after domain work before allowing the commit.
    fence(session, run, capability)
    session.commit()
    return result.model_dump(mode="json")
