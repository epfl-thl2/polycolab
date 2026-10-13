"""Validated agent proposal storage; it never mutates canonical research directly."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from polycolab.access.actors import human_actor
from polycolab.access.authorization import ProjectAction, project_policy
from polycolab.agents.proposal_version_schemas import (
    ObjectVersionProposalChange,
    ProposeCommentCreate,
    ProposeObjectCreate,
    ProposeObjectVersionCreate,
    ProposeRelationshipCreate,
    proposal_change_adapter,
)
from polycolab.db.models import (
    SqlAgentRunEvent,
    SqlContributionEnvelope,
    SqlProposal,
    SqlProposalChange,
    SqlProposalChangeDecision,
    SqlProposalDecisionBatch,
    SqlResearchScope,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.accounts import IdentifiedUser
from polycolab.entities.enums import (
    AgentRunEventKind,
    CanonicalEntityType,
    ContributionActorKind,
    ProposalChangeStatus,
    ProposalChangeType,
    ProposalDecisionAction,
    ProvenanceKind,
    RelationType,
    ResearchObjectKind,
)
from polycolab.entities.time import utc_now
from polycolab.platform.observability import metrics
from polycolab.projects.service import DomainConflict
from polycolab.research.contracts import ProofStructureWrite
from polycolab.research.objects import (
    ResearchNotFound,
    StaleRevision,
    create_comment,
    create_object,
    create_relation,
    create_revision,
    object_in_project,
    revision_in_project,
)
from polycolab.research.schemas import ResearchAttemptRequest
from polycolab.research.version_schemas import BidirectionalRelationshipInput


class ProposalInvalid(Exception):
    pass


class ProposalNotFound(Exception):
    pass


class ProposalStale(DomainConflict):
    def __init__(self, change_id: UUID, current_revision_id: UUID | None) -> None:
        self.change_id = change_id
        self.current_revision_id = current_revision_id


@dataclass(frozen=True)
class BatchDecisionInput:
    change_id: UUID
    action: ProposalDecisionAction
    payload: dict[str, object] | None
    reason: str | None


@dataclass(frozen=True)
class _PreparedBatchDecision:
    change: SqlProposalChange
    action: ProposalDecisionAction
    payload: dict[str, object] | None
    reason: str | None
    request_digest: str


def decision_key_digest(value: str) -> str:
    if (
        not value
        or len(value) > 200
        or value != value.strip()
        or any(ord(character) < 33 or ord(character) == 127 for character in value)
    ):
        raise ProposalInvalid
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _decision_request_digest(action: ProposalDecisionAction, value: object) -> str:
    canonical = json.dumps(
        {"action": action.value, "value": value}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _batch_request_digest(decisions: list[_PreparedBatchDecision]) -> str:
    canonical = json.dumps(
        [
            {
                "change_id": str(item.change.id),
                "action": item.action.value,
                "payload": item.payload,
                "reason": item.reason,
            }
            for item in sorted(decisions, key=lambda item: str(item.change.id))
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_decision_replay(
    session: Session,
    *,
    change: SqlProposalChange,
    decider: IdentifiedUser,
    action: ProposalDecisionAction,
    idempotency_key_digest: str,
    request_digest: str,
    historical_request_digest: str | None = None,
) -> bool:
    decision = session.scalar(
        select(SqlProposalChangeDecision).where(
            SqlProposalChangeDecision.proposal_change_id == change.id
        )
    )
    if decision is None:
        return False
    if (
        decision.action is action
        and decision.decided_by_user_id == decider.id
        and decision.idempotency_key_digest == idempotency_key_digest
        and decision.request_digest in {request_digest, historical_request_digest}
    ):
        return True
    raise DomainConflict


def _historical_edited_payload(
    session: Session, change: SqlProposalChange, payload: dict[str, object] | None
) -> dict[str, object] | None:
    """Recover only an exact, representable stored edit for digest verification.

    This does not accept legacy HTTP writes or rewrite stored decisions. The caller
    must still match the original digest, reviewer, key, action and batch membership.
    """
    if payload is None or change.status is not ProposalChangeStatus.ACCEPTED:
        return None
    stored = validate_change(change.payload)
    if not isinstance(
        stored,
        (CreateObjectPayload, CreateRevisionPayload, CreateRelationPayload, CreateCommentPayload),
    ):
        return None
    from polycolab.agents.proposal_projections import proposal_payload_read

    projected = proposal_payload_read(session, project_id=change.project_id, payload=change.payload)
    try:
        normalized = proposal_change_adapter.validate_python(projected).model_dump(mode="json")
    except ValueError:
        # Some historical content cannot be represented by today's write contract.
        return None
    return stored.model_dump(mode="json") if normalized == payload else None


class CreateObjectPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[ProposalChangeType.CREATE_OBJECT]
    object_kind: ResearchObjectKind
    title: str = Field(min_length=1, max_length=500)
    content_md: str = Field(min_length=1, max_length=200_000)
    rationale: str | None = Field(default=None, max_length=20_000)
    proof_sketch: ProofStructureWrite | None = None
    attempt: ResearchAttemptRequest | None = None

    @model_validator(mode="after")
    def coherent(self) -> CreateObjectPayload:
        if self.object_kind is ResearchObjectKind.PROOF:
            raise ValueError("new proof approaches must use PROOF_SKETCH")
        if (self.object_kind in {ResearchObjectKind.PROOF, ResearchObjectKind.PROOF_SKETCH}) != (
            self.proof_sketch is not None
        ):
            raise ValueError("proof structure is required exactly for proof-sketch records")
        if (self.object_kind is ResearchObjectKind.ATTEMPT) != (self.attempt is not None):
            raise ValueError("attempt structure is required exactly for attempt records")
        return self


class CreateRevisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[ProposalChangeType.CREATE_REVISION]
    object_id: UUID
    base_revision_id: UUID
    title: str = Field(min_length=1, max_length=500)
    content_md: str = Field(min_length=1, max_length=200_000)
    rationale: str | None = Field(default=None, max_length=20_000)
    proof_sketch: ProofStructureWrite | None = None
    attempt: ResearchAttemptRequest | None = None


class CreateRelationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[ProposalChangeType.CREATE_RELATION]
    source_revision_id: UUID
    target_revision_id: UUID
    relation_type: RelationType
    rationale: str = Field(min_length=1, max_length=20_000)


class CreateCommentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[ProposalChangeType.CREATE_COMMENT]
    object_id: UUID
    revision_id: UUID
    body_md: str = Field(min_length=1, max_length=50_000)


ChangePayload = Annotated[
    CreateObjectPayload | CreateRevisionPayload | CreateRelationPayload | CreateCommentPayload,
    Field(discriminator="kind"),
]
_payload_adapter: TypeAdapter[ChangePayload] = TypeAdapter(ChangePayload)


StoredChangePayload = ChangePayload | ObjectVersionProposalChange


def validate_change(value: dict[str, object]) -> StoredChangePayload:
    try:
        if (
            value.get("kind") in {"CREATE_OBJECT_VERSION", "CREATE_RELATIONSHIP"}
            or "snapshot" in value
            or "object_version_id" in value
        ):
            return proposal_change_adapter.validate_python(value)
        return _payload_adapter.validate_python(value)
    except Exception as exc:
        raise ProposalInvalid from exc


def change_type(payload: StoredChangePayload) -> ProposalChangeType:
    """Keep the persisted operation enum stable across payload generations."""
    if isinstance(payload, ProposeObjectVersionCreate):
        return ProposalChangeType.CREATE_REVISION
    if isinstance(payload, ProposeRelationshipCreate):
        return ProposalChangeType.CREATE_RELATION
    return ProposalChangeType(payload.kind)


def _validate_version_scope(
    session: Session,
    *,
    payload: StoredChangePayload,
    project_id: UUID,
    allowed: set[UUID],
) -> None:
    pins: set[UUID] = set()
    object_pin: tuple[UUID, UUID] | None = None
    if isinstance(payload, (ProposeObjectCreate, ProposeObjectVersionCreate)):
        pins.update(r.target_object_version_id for r in payload.snapshot.structural_relationships)
        if isinstance(payload, ProposeObjectVersionCreate):
            object_pin = (payload.object_id, payload.expected_current_object_version_id)
    elif isinstance(payload, ProposeRelationshipCreate):
        relationship = payload.relationship
        if isinstance(relationship, BidirectionalRelationshipInput):
            pins.update(
                (relationship.first_object_version_id, relationship.second_object_version_id)
            )
        else:
            pins.update(
                (relationship.source_object_version_id, relationship.target_object_version_id)
            )
    elif isinstance(payload, ProposeCommentCreate):
        object_pin = (payload.object_id, payload.object_version_id)
    if object_pin is not None:
        object_id, version_id = object_pin
        pins.add(version_id)
        if version_id not in allowed:
            raise ProposalInvalid
        if (
            revision_in_project(session, project_id=project_id, revision_id=version_id).object_id
            != object_id
        ):
            raise ProposalInvalid
    if not pins <= allowed:
        raise ProposalInvalid


def submit_proposal(
    session: Session,
    *,
    project_id: UUID,
    session_id: UUID,
    run_id: UUID,
    agent_version_id: UUID,
    context_manifest_id: UUID,
    idempotency_key: str,
    summary: str,
    changes: list[dict[str, object]],
    trusted_source_event_cursors: list[int] | None = None,
    trusted_source_invocation_key: str | None = None,
) -> SqlProposal:
    if not idempotency_key or len(idempotency_key) > 200 or not summary.strip() or not changes:
        raise ProposalInvalid
    source_event_cursors = trusted_source_event_cursors
    if (
        not source_event_cursors
        or not trusted_source_invocation_key
        or len(trusted_source_invocation_key) > 180
        or len(source_event_cursors) != len(set(source_event_cursors))
        or any(cursor <= 0 for cursor in source_event_cursors)
    ):
        raise ProposalInvalid
    source_events = list(
        session.scalars(
            select(SqlAgentRunEvent).where(
                SqlAgentRunEvent.run_id == run_id,
                SqlAgentRunEvent.cursor.in_(source_event_cursors),
            )
        )
    )
    if {item.cursor for item in source_events} != set(source_event_cursors) or any(
        item.kind is not AgentRunEventKind.TOOL_REQUESTED
        or item.payload.get("tool_name") != "submit_proposal"
        or item.idempotency_key != f"{trusted_source_invocation_key}-requested"
        for item in source_events
    ):
        raise ProposalInvalid
    parsed = [validate_change(value) for value in changes]
    existing = session.scalar(
        select(SqlProposal).where(
            SqlProposal.run_id == run_id, SqlProposal.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        stored = list(
            session.scalars(
                select(SqlProposalChange)
                .where(SqlProposalChange.proposal_id == existing.id)
                .order_by(SqlProposalChange.ordinal)
            )
        )
        if (
            existing.summary != summary
            or [item.payload for item in stored]
            != [item.model_dump(mode="json") for item in parsed]
            or any(item.source_event_cursors != source_event_cursors for item in stored)
        ):
            raise ProposalInvalid from None
        return existing
    # The manifest is immutable and passed from the authorized tool call.  The
    # proposal can only refer to revisions the run was explicitly allowed to see.
    from polycolab.agents.context import manifest_revisions
    from polycolab.db.models import SqlContextManifest

    manifest = session.get(SqlContextManifest, context_manifest_id)
    if manifest is None or manifest.run_id != run_id or manifest.project_id != project_id:
        raise ProposalInvalid
    allowed_revision_ids = {item.id for item in manifest_revisions(session, manifest=manifest)}
    for payload in parsed:
        _validate_version_scope(
            session, payload=payload, project_id=project_id, allowed=allowed_revision_ids
        )
        if isinstance(payload, CreateRevisionPayload):
            if payload.base_revision_id not in allowed_revision_ids:
                raise ProposalInvalid
            base = revision_in_project(
                session, project_id=project_id, revision_id=payload.base_revision_id
            )
            if base.object_id != payload.object_id:
                raise ProposalInvalid
        elif isinstance(payload, CreateRelationPayload):
            if (
                payload.source_revision_id not in allowed_revision_ids
                or payload.target_revision_id not in allowed_revision_ids
            ):
                raise ProposalInvalid
        elif isinstance(payload, CreateCommentPayload):
            if payload.revision_id not in allowed_revision_ids:
                raise ProposalInvalid
            if (
                revision_in_project(
                    session, project_id=project_id, revision_id=payload.revision_id
                ).object_id
                != payload.object_id
            ):
                raise ProposalInvalid
    proposal = SqlProposal(
        project_id=project_id,
        session_id=session_id,
        run_id=run_id,
        agent_version_id=agent_version_id,
        context_manifest_id=context_manifest_id,
        requested_by_user_id=manifest.requested_by_user_id,
        idempotency_key=idempotency_key,
        summary=summary,
    )
    session.add(proposal)
    session.flush()
    for ordinal, payload in enumerate(parsed, start=1):
        session.add(
            SqlProposalChange(
                proposal_id=proposal.id,
                project_id=project_id,
                ordinal=ordinal,
                change_type=change_type(payload),
                payload=payload.model_dump(mode="json"),
                source_event_cursors=source_event_cursors,
            )
        )
    try:
        session.commit()
    except IntegrityError:
        # A recovered worker may race the original invocation.  The database
        # unique key is authoritative; after releasing the failed transaction,
        # return only an identical already-committed proposal.
        session.rollback()
        replay = session.scalar(
            select(SqlProposal).where(
                SqlProposal.run_id == run_id, SqlProposal.idempotency_key == idempotency_key
            )
        )
        if replay is None:
            raise ProposalInvalid from None
        stored = list(
            session.scalars(
                select(SqlProposalChange)
                .where(SqlProposalChange.proposal_id == replay.id)
                .order_by(SqlProposalChange.ordinal)
            )
        )
        if (
            replay.summary != summary
            or [item.payload for item in stored]
            != [item.model_dump(mode="json") for item in parsed]
            or any(item.source_event_cursors != source_event_cursors for item in stored)
        ):
            raise ProposalInvalid from None
        return replay
    session.refresh(proposal)
    return proposal


def pending_changes(session: Session, *, proposal_id: UUID) -> list[SqlProposalChange]:
    return list(
        session.scalars(
            select(SqlProposalChange)
            .where(
                SqlProposalChange.proposal_id == proposal_id,
                SqlProposalChange.status == ProposalChangeStatus.PENDING,
            )
            .order_by(SqlProposalChange.ordinal)
        )
    )


def proposal_in_project(session: Session, *, proposal_id: UUID, project_id: UUID) -> SqlProposal:
    value = session.scalar(
        select(SqlProposal).where(
            SqlProposal.id == proposal_id, SqlProposal.project_id == project_id
        )
    )
    if value is None:
        raise ProposalNotFound
    return value


def changes_for_proposal(session: Session, *, proposal_id: UUID) -> list[SqlProposalChange]:
    return list(
        session.scalars(
            select(SqlProposalChange)
            .where(SqlProposalChange.proposal_id == proposal_id)
            .order_by(SqlProposalChange.ordinal)
        )
    )


def _apply_change(
    session: Session, *, change: SqlProposalChange, proposal: SqlProposal, decider: IdentifiedUser
) -> tuple[UUID, CanonicalEntityType]:
    payload = validate_change(change.payload)
    scope_id = session.scalar(
        select(SqlResearchScope.id).where(SqlResearchScope.project_id == proposal.project_id)
    )
    contribution = SqlContributionEnvelope(
        actor_kind=ContributionActorKind.AGENT,
        sponsor_user_id=proposal.requested_by_user_id,
        agent_version_id=proposal.agent_version_id,
        run_id=proposal.run_id,
        session_id=proposal.session_id,
        context_manifest_id=proposal.context_manifest_id,
        ownership_scope_id=scope_id,
        project_id=proposal.project_id,
        operation="PROPOSAL_REVIEW",
        proposal_change_id=change.id,
        decided_by_user_id=decider.id,
        source_event_cursors=list(change.source_event_cursors),
    )
    session.add(contribution)
    session.flush()
    try:
        if isinstance(payload, (ProposeObjectCreate, ProposeObjectVersionCreate)):
            from polycolab.research.records import write_record
            from polycolab.research.version_commands import snapshot_command

            editing = isinstance(payload, ProposeObjectVersionCreate)
            if isinstance(payload, ProposeObjectVersionCreate):
                current = object_in_project(
                    session, project_id=proposal.project_id, object_id=payload.object_id
                )
                if current.current_revision_id != payload.expected_current_object_version_id:
                    raise ProposalStale(change.id, current.current_revision_id)
            command = snapshot_command(
                payload.snapshot,
                project_id=proposal.project_id,
                object_id=payload.object_id
                if isinstance(payload, ProposeObjectVersionCreate)
                else None,
                expected_current_object_version_id=(
                    payload.expected_current_object_version_id
                    if isinstance(payload, ProposeObjectVersionCreate)
                    else None
                ),
            )
            result = write_record(
                session,
                actor=human_actor(decider.id),
                payload=command,
                key=f"proposal:{change.id}",
                contribution=contribution,
                commit=False,
            )
            if editing:
                assert result.revision_id is not None
                return result.revision_id, CanonicalEntityType.OBJECT_REVISION
            return result.id, CanonicalEntityType.RESEARCH_OBJECT
        if isinstance(payload, ProposeRelationshipCreate):
            from polycolab.research.contracts import SnapshotRelationWrite
            from polycolab.research.records import write_relation

            relationship = payload.relationship
            first, second = (
                (relationship.first_object_version_id, relationship.second_object_version_id)
                if isinstance(relationship, BidirectionalRelationshipInput)
                else (relationship.source_object_version_id, relationship.target_object_version_id)
            )
            relation_result = write_relation(
                session,
                actor=human_actor(decider.id),
                payload=SnapshotRelationWrite(
                    project_id=proposal.project_id,
                    source_revision_id=first,
                    target_revision_id=second,
                    relation_type=relationship.relationship_type,
                    rationale=relationship.description or "Proposed relationship",
                    description=relationship.description,
                ),
                key=f"proposal:{change.id}",
                contribution=contribution,
                commit=False,
            )
            return relation_result.id, CanonicalEntityType.RELATION_ASSERTION
        if isinstance(payload, ProposeCommentCreate):
            comment_result = create_comment(
                session,
                project_id=proposal.project_id,
                object_id=payload.object_id,
                revision_id=payload.object_version_id,
                body_md=payload.body_md,
                author=decider,
                provenance_kind=ProvenanceKind.AGENT_PROPOSAL,
                contribution=contribution,
                commit=False,
                actor=human_actor(decider.id),
            )
            return comment_result.id, CanonicalEntityType.RESEARCH_COMMENT
        if isinstance(payload, CreateObjectPayload):
            research_object, _revision = create_object(
                session,
                project_id=proposal.project_id,
                kind=payload.object_kind,
                title=payload.title,
                content_md=payload.content_md,
                rationale=payload.rationale,
                proof=payload.proof_sketch,
                attempt=payload.attempt,
                author=decider,
                provenance_kind=ProvenanceKind.AGENT_PROPOSAL,
                contribution=contribution,
                commit=False,
                actor=human_actor(decider.id),
            )
            return research_object.id, CanonicalEntityType.RESEARCH_OBJECT
        if isinstance(payload, CreateRevisionPayload):
            object_value = object_in_project(
                session, project_id=proposal.project_id, object_id=payload.object_id
            )
            if object_value.current_revision_id != payload.base_revision_id:
                raise ProposalStale(change.id, object_value.current_revision_id)
            _object, revision = create_revision(
                session,
                project_id=proposal.project_id,
                object_id=payload.object_id,
                base_revision_id=payload.base_revision_id,
                title=payload.title,
                content_md=payload.content_md,
                rationale=payload.rationale,
                proof=payload.proof_sketch,
                attempt=payload.attempt,
                author=decider,
                provenance_kind=ProvenanceKind.AGENT_PROPOSAL,
                contribution=contribution,
                commit=False,
                actor=human_actor(decider.id),
            )
            return revision.id, CanonicalEntityType.OBJECT_REVISION
        if isinstance(payload, CreateRelationPayload):
            relation = create_relation(
                session,
                project_id=proposal.project_id,
                source_revision_id=payload.source_revision_id,
                target_revision_id=payload.target_revision_id,
                relation_type=payload.relation_type,
                rationale=payload.rationale,
                author=decider,
                provenance_kind=ProvenanceKind.AGENT_PROPOSAL,
                contribution=contribution,
                commit=False,
                actor=human_actor(decider.id),
            )
            return relation.id, CanonicalEntityType.RELATION_ASSERTION
        comment = create_comment(
            session,
            project_id=proposal.project_id,
            object_id=payload.object_id,
            revision_id=payload.revision_id,
            body_md=payload.body_md,
            author=decider,
            provenance_kind=ProvenanceKind.AGENT_PROPOSAL,
            contribution=contribution,
            commit=False,
            actor=human_actor(decider.id),
        )
        return comment.id, CanonicalEntityType.RESEARCH_COMMENT
    except StaleRevision:
        if not isinstance(payload, CreateRevisionPayload):
            raise ProposalInvalid from None
        object_value = object_in_project(
            session, project_id=proposal.project_id, object_id=payload.object_id
        )
        raise ProposalStale(change.id, object_value.current_revision_id) from None
    except ResearchNotFound:
        raise ProposalStale(change.id, None) from None


def _validate_application_scope(
    session: Session, *, proposal: SqlProposal, payload: StoredChangePayload
) -> None:
    """Edited acceptance keeps the same explicit run-context boundary."""
    from polycolab.agents.context import manifest_revisions
    from polycolab.db.models import SqlContextManifest

    manifest = session.get(SqlContextManifest, proposal.context_manifest_id)
    if manifest is None:
        raise ProposalInvalid
    allowed = {item.id for item in manifest_revisions(session, manifest=manifest)}
    _validate_version_scope(
        session, payload=payload, project_id=proposal.project_id, allowed=allowed
    )
    if isinstance(payload, CreateRevisionPayload):
        if payload.base_revision_id not in allowed:
            raise ProposalInvalid
        revision = revision_in_project(
            session, project_id=proposal.project_id, revision_id=payload.base_revision_id
        )
        if revision.object_id != payload.object_id:
            raise ProposalInvalid
    elif isinstance(payload, CreateRelationPayload):
        if payload.source_revision_id not in allowed or payload.target_revision_id not in allowed:
            raise ProposalInvalid
    elif isinstance(payload, CreateCommentPayload):
        if payload.revision_id not in allowed:
            raise ProposalInvalid
        if (
            revision_in_project(
                session, project_id=proposal.project_id, revision_id=payload.revision_id
            ).object_id
            != payload.object_id
        ):
            raise ProposalInvalid


def accept_change(
    session: Session,
    *,
    proposal: SqlProposal,
    change_id: UUID,
    decider: IdentifiedUser,
    idempotency_key: str,
    edited_payload: dict[str, object] | None = None,
) -> SqlProposalChange:
    """Apply exactly one pending change as one canonical/review transaction.

    Replays return the original accepted change. A different edit is a conflict,
    never a silent second mutation.
    """
    project_policy.require_scope(
        SqlAlchemyTransaction(session),
        proposal.project_id,
        decider.id,
        ProjectAction.REVIEW_PROPOSALS,
    )
    change = session.scalar(
        select(SqlProposalChange)
        .where(SqlProposalChange.id == change_id, SqlProposalChange.proposal_id == proposal.id)
        .with_for_update()
    )
    if change is None:
        raise ProposalNotFound
    key_digest = decision_key_digest(idempotency_key)
    if edited_payload is not None:
        parsed = validate_change(edited_payload)
        if change_type(parsed) != change.change_type:
            raise ProposalInvalid
        proposed_payload = parsed.model_dump(mode="json")
    else:
        proposed_payload = change.payload
    request_digest = _decision_request_digest(
        ProposalDecisionAction.ACCEPT,
        parsed.model_dump(mode="json") if edited_payload is not None else None,
    )
    if change.status is ProposalChangeStatus.ACCEPTED:
        historical = _historical_edited_payload(
            session, change, proposed_payload if edited_payload is not None else None
        )
        if _is_decision_replay(
            session,
            change=change,
            decider=decider,
            action=ProposalDecisionAction.ACCEPT,
            idempotency_key_digest=key_digest,
            request_digest=request_digest,
            historical_request_digest=_decision_request_digest(
                ProposalDecisionAction.ACCEPT, historical
            )
            if historical is not None
            else None,
        ):
            return change
        raise DomainConflict
    if change.status is ProposalChangeStatus.REJECTED:
        raise DomainConflict
    if edited_payload is not None:
        change.payload = proposed_payload
    try:
        _validate_application_scope(
            session, proposal=proposal, payload=validate_change(change.payload)
        )
        entity_id, entity_type = _apply_change(
            session, change=change, proposal=proposal, decider=decider
        )
        change.status = ProposalChangeStatus.ACCEPTED
        change.decided_by_user_id = decider.id
        change.decided_at = utc_now()
        change.applied_entity_id = entity_id
        session.add(
            SqlProposalChangeDecision(
                proposal_change_id=change.id,
                project_id=proposal.project_id,
                action=ProposalDecisionAction.ACCEPT,
                idempotency_key_digest=key_digest,
                request_digest=request_digest,
                decided_by_user_id=decider.id,
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(change)
    metrics.increment("polycolab_proposal_decisions_total", decision="ACCEPT")
    return change


def reject_change(
    session: Session,
    *,
    proposal: SqlProposal,
    change_id: UUID,
    decider: IdentifiedUser,
    idempotency_key: str,
    reason: str | None,
) -> SqlProposalChange:
    change = session.scalar(
        select(SqlProposalChange)
        .where(SqlProposalChange.id == change_id, SqlProposalChange.proposal_id == proposal.id)
        .with_for_update()
    )
    if change is None:
        raise ProposalNotFound
    key_digest = decision_key_digest(idempotency_key)
    request_digest = _decision_request_digest(ProposalDecisionAction.REJECT, reason)
    if change.status is ProposalChangeStatus.REJECTED:
        if _is_decision_replay(
            session,
            change=change,
            decider=decider,
            action=ProposalDecisionAction.REJECT,
            idempotency_key_digest=key_digest,
            request_digest=request_digest,
        ):
            return change
        raise DomainConflict
    if change.status is ProposalChangeStatus.ACCEPTED:
        raise DomainConflict
    change.status = ProposalChangeStatus.REJECTED
    change.decided_by_user_id = decider.id
    change.decided_at = utc_now()
    change.rejection_reason = reason
    session.add(
        SqlProposalChangeDecision(
            proposal_change_id=change.id,
            project_id=proposal.project_id,
            action=ProposalDecisionAction.REJECT,
            idempotency_key_digest=key_digest,
            request_digest=request_digest,
            decided_by_user_id=decider.id,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise DomainConflict from None
    session.refresh(change)
    metrics.increment("polycolab_proposal_decisions_total", decision="REJECT")
    return change


def decide_changes_atomically(
    session: Session,
    *,
    proposal: SqlProposal,
    decider: IdentifiedUser,
    idempotency_key: str,
    decisions: list[BatchDecisionInput],
) -> list[SqlProposalChange]:
    """Review a selected set as one transaction, with no partial decision state."""
    project_policy.require_scope(
        SqlAlchemyTransaction(session),
        proposal.project_id,
        decider.id,
        ProjectAction.REVIEW_PROPOSALS,
    )
    if not decisions or len({item.change_id for item in decisions}) != len(decisions):
        raise ProposalInvalid
    key_digest = decision_key_digest(idempotency_key)
    requested_ids = {item.change_id for item in decisions}
    changes = list(
        session.scalars(
            select(SqlProposalChange)
            .where(
                SqlProposalChange.proposal_id == proposal.id,
                SqlProposalChange.id.in_(requested_ids),
            )
            .order_by(SqlProposalChange.id)
            .with_for_update()
        )
    )
    if len(changes) != len(requested_ids):
        raise ProposalNotFound
    by_id = {item.id: item for item in changes}
    prepared: list[_PreparedBatchDecision] = []
    for request in decisions:
        change = by_id[request.change_id]
        if request.action is ProposalDecisionAction.ACCEPT:
            if request.reason is not None:
                raise ProposalInvalid
            payload = None
            if request.payload is not None:
                parsed = validate_change(request.payload)
                if change_type(parsed) != change.change_type:
                    raise ProposalInvalid
                payload = parsed.model_dump(mode="json")
            effective_payload = payload if payload is not None else change.payload
            _validate_application_scope(
                session, proposal=proposal, payload=validate_change(effective_payload)
            )
            prepared.append(
                _PreparedBatchDecision(
                    change=change,
                    action=request.action,
                    payload=payload,
                    reason=None,
                    request_digest=_decision_request_digest(request.action, payload),
                )
            )
        else:
            if request.payload is not None:
                raise ProposalInvalid
            prepared.append(
                _PreparedBatchDecision(
                    change=change,
                    action=request.action,
                    payload=None,
                    reason=request.reason,
                    request_digest=_decision_request_digest(request.action, request.reason),
                )
            )
    batch_digest = _batch_request_digest(prepared)
    recorded = session.scalar(
        select(SqlProposalDecisionBatch).where(
            SqlProposalDecisionBatch.proposal_id == proposal.id,
            SqlProposalDecisionBatch.idempotency_key_digest == key_digest,
        )
    )
    if recorded is not None:
        if recorded.decided_by_user_id != decider.id:
            raise DomainConflict
        if recorded.request_digest != batch_digest:
            historical_prepared = []
            for item in prepared:
                historical = _historical_edited_payload(session, item.change, item.payload)
                historical_prepared.append(
                    replace(item, payload=historical) if historical is not None else item
                )
            if recorded.request_digest != _batch_request_digest(historical_prepared):
                raise DomainConflict
        return [by_id[item.change_id] for item in decisions]
    if any(item.change.status is not ProposalChangeStatus.PENDING for item in prepared):
        raise DomainConflict
    try:
        session.add(
            SqlProposalDecisionBatch(
                proposal_id=proposal.id,
                project_id=proposal.project_id,
                idempotency_key_digest=key_digest,
                request_digest=batch_digest,
                decided_by_user_id=decider.id,
            )
        )
        for item in prepared:
            change = item.change
            if item.action is ProposalDecisionAction.ACCEPT:
                if item.payload is not None:
                    change.payload = item.payload
                entity_id, entity_type = _apply_change(
                    session, change=change, proposal=proposal, decider=decider
                )
                change.status = ProposalChangeStatus.ACCEPTED
                change.decided_by_user_id = decider.id
                change.decided_at = utc_now()
                change.applied_entity_id = entity_id
            else:
                change.status = ProposalChangeStatus.REJECTED
                change.decided_by_user_id = decider.id
                change.decided_at = utc_now()
                change.rejection_reason = item.reason
            session.add(
                SqlProposalChangeDecision(
                    proposal_change_id=change.id,
                    project_id=proposal.project_id,
                    action=item.action,
                    idempotency_key_digest=key_digest,
                    request_digest=item.request_digest,
                    decided_by_user_id=decider.id,
                )
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    for change in changes:
        session.refresh(change)
    for item in prepared:
        metrics.increment("polycolab_proposal_decisions_total", decision=item.action.value)
    return [by_id[item.change_id] for item in decisions]
