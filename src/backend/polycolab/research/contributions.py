"""Attributable contribution envelopes and atomic mutation receipts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor, ActorKind, ActorOperation
from polycolab.access.authorization import (
    ProjectAction,
    lock_project_authorization,
    project_policy,
    require_project_write,
)
from polycolab.db.models import (
    SqlContributionEntityLink,
    SqlContributionEnvelope,
    SqlMutationReceipt,
    SqlObjectRevision,
    SqlRelationAssertion,
    SqlResearchComment,
    SqlResearchObject,
    SqlResearchScope,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import (
    CanonicalEntityType,
    ContributionActorKind,
    MutationReceiptStatus,
    ResearchScopeKind,
)
from polycolab.platform.outbox import append_event, canonical_digest


class ContributionConflict(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ContributionOutput:
    canonical_entity_type: str
    canonical_entity_id: UUID
    ownership_scope_id: UUID


@dataclass(frozen=True, slots=True)
class ContributionMutation:
    envelope: SqlContributionEnvelope
    links: tuple[SqlContributionEntityLink, ...]
    receipt: SqlMutationReceipt
    replayed: bool


def _actor_key(actor: Actor) -> str:
    if actor.kind is ActorKind.HUMAN and actor.human_user_id is not None:
        return f"human:{actor.human_user_id}"
    if actor.kind is ActorKind.AGENT and (
        actor.run_id is not None or actor.external_run_id is not None
    ):
        return f"agent:{actor.run_id or actor.external_run_id}"
    raise ContributionConflict


def _envelope_values(actor: Actor) -> dict[str, object]:
    if actor.kind is ActorKind.HUMAN:
        if actor.human_user_id is None:
            raise ContributionConflict
        return {
            "actor_kind": ContributionActorKind.HUMAN,
            "human_user_id": actor.human_user_id,
        }
    if actor.sponsor_user_id is None:
        raise ContributionConflict
    if actor.external_credential_id is not None and actor.external_agent_id is not None:
        return {
            "actor_kind": ContributionActorKind.AGENT,
            "sponsor_user_id": actor.sponsor_user_id,
            "project_id": actor.project_id,
            "external_credential_id": actor.external_credential_id,
            "external_agent_id": actor.external_agent_id,
        }
    if actor.external_credential_id is not None and actor.external_run_id is not None:
        return {
            "actor_kind": ContributionActorKind.AGENT,
            "sponsor_user_id": actor.sponsor_user_id,
            "project_id": actor.project_id,
            "external_credential_id": actor.external_credential_id,
            "external_run_id": actor.external_run_id,
        }
    if (
        actor.agent_version_id is None
        or actor.run_id is None
        or actor.capability_id is None
        or actor.session_id is None
        or actor.context_manifest_id is None
    ):
        raise ContributionConflict
    return {
        "actor_kind": ContributionActorKind.AGENT,
        "sponsor_user_id": actor.sponsor_user_id,
        "project_id": actor.project_id,
        "agent_version_id": actor.agent_version_id,
        "run_id": actor.run_id,
        "session_id": actor.session_id,
        "context_manifest_id": actor.context_manifest_id,
    }


def _replayed_mutation(
    session: Session, receipt: SqlMutationReceipt, *, request_digest: str
) -> ContributionMutation:
    if receipt.request_digest != request_digest:
        raise ContributionConflict
    if receipt.status is not MutationReceiptStatus.COMMITTED or not receipt.resource_ids:
        raise ContributionConflict
    envelope_id = UUID(receipt.resource_ids[0])
    envelope = session.get(SqlContributionEnvelope, envelope_id)
    if envelope is None:
        raise ContributionConflict
    links_by_id = {
        str(link.id): link
        for link in session.scalars(
            select(SqlContributionEntityLink).where(
                SqlContributionEntityLink.envelope_id == envelope.id
            )
        )
    }
    # The receipt preserves the original result order; random UUID order does not.
    link_ids = receipt.resource_ids[1:]
    if len(link_ids) != len(set(link_ids)) or not set(link_ids) <= set(links_by_id):
        raise ContributionConflict
    links = tuple(links_by_id[link_id] for link_id in link_ids)
    return ContributionMutation(envelope, links, receipt, replayed=True)


def record_contribution(
    session: Session,
    *,
    actor: Actor,
    operation: str,
    idempotency_key: str,
    request_payload: object,
    outputs: list[ContributionOutput] | None = None,
    create_outputs: Callable[[SqlContributionEnvelope], list[ContributionOutput]] | None = None,
    ownership_scope_id: UUID | None = None,
    proposal_change_id: UUID | None = None,
    decided_by_user_id: UUID | None = None,
    source_event_cursors: list[int] | None = None,
    commit: bool = True,
) -> ContributionMutation:
    """Record existing outputs or create them after checking a durable receipt.

    New content must be created by create_outputs with commit=False research
    primitives, so retries never execute the content mutation a second time.
    M0 exposes this composition only for authorized human project writes;
    direct agent writes need the run/output policy introduced in M1.
    """

    if not 1 <= len(operation) <= 64 or not 1 <= len(idempotency_key) <= 200:
        raise ContributionConflict
    if (outputs is None) == (create_outputs is None):
        raise ContributionConflict
    source_event_cursors = list(source_event_cursors or [])
    if any(cursor < 1 for cursor in source_event_cursors):
        raise ContributionConflict
    actor_key = _actor_key(actor)
    if session.get_bind().dialect.name == "postgresql":
        lock_digest = canonical_digest([actor_key, operation, idempotency_key])
        lock_key = int(lock_digest[:16], 16)
        if lock_key >= 2**63:
            lock_key -= 2**64
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    scope = session.get(SqlResearchScope, ownership_scope_id) if ownership_scope_id else None
    if (
        scope is None
        or scope.scope_kind is not ResearchScopeKind.PROJECT
        or scope.project_id is None
    ):
        raise ContributionConflict
    authority_user_id = actor.human_user_id or actor.sponsor_user_id
    if authority_user_id is None:
        raise ContributionConflict
    if actor.kind is ActorKind.AGENT:
        require_project_write(actor, project_id=scope.project_id)
        if ActorOperation.CONTRIBUTION_CREATE not in actor.operation_scope:
            raise ContributionConflict
        if actor.ownership_scope_id != scope.id:
            raise ContributionConflict
    lock_project_authorization(
        SqlAlchemyTransaction(session), project_id=scope.project_id, user_id=authority_user_id
    )
    project_policy.require_scope(
        SqlAlchemyTransaction(session),
        scope.project_id,
        authority_user_id,
        ProjectAction.CREATE_RESEARCH,
    )
    if proposal_change_id is not None or decided_by_user_id is not None or source_event_cursors:
        raise ContributionConflict
    request_digest = canonical_digest(
        {
            "schema_version": 1,
            "payload": request_payload,
            "scope": str(scope.id),
            "outputs": [
                (o.canonical_entity_type, str(o.canonical_entity_id), str(o.ownership_scope_id))
                for o in outputs
            ]
            if outputs is not None
            else None,
        }
    )
    idempotency_digest = canonical_digest(idempotency_key)
    existing = session.scalar(
        select(SqlMutationReceipt)
        .where(
            SqlMutationReceipt.actor_key == actor_key,
            SqlMutationReceipt.operation == operation,
            SqlMutationReceipt.idempotency_key_digest == idempotency_digest,
        )
        .with_for_update()
    )
    if existing is not None:
        replay = _replayed_mutation(session, existing, request_digest=request_digest)
        if commit:
            session.commit()
        return replay

    try:
        values = _envelope_values(actor)
        envelope = SqlContributionEnvelope(
            **values,
            ownership_scope_id=ownership_scope_id,
            operation=operation,
            proposal_change_id=proposal_change_id,
            decided_by_user_id=decided_by_user_id,
            source_event_cursors=source_event_cursors,
        )
        session.add(envelope)
        session.flush()
        if create_outputs is not None:
            outputs = create_outputs(envelope)
        if outputs is None or not 1 <= len(outputs) <= 100:
            raise ContributionConflict
        # Receipts must contain each result link once so every successful write
        # can be replayed. Reject duplicates inside the rollback boundary.
        output_keys = [
            (output.canonical_entity_type, output.canonical_entity_id) for output in outputs
        ]
        if len(output_keys) != len(set(output_keys)):
            raise ContributionConflict
        entity_models: dict[
            CanonicalEntityType,
            type[SqlResearchObject]
            | type[SqlObjectRevision]
            | type[SqlRelationAssertion]
            | type[SqlResearchComment],
        ] = {
            CanonicalEntityType.RESEARCH_OBJECT: SqlResearchObject,
            CanonicalEntityType.OBJECT_REVISION: SqlObjectRevision,
            CanonicalEntityType.RELATION_ASSERTION: SqlRelationAssertion,
            CanonicalEntityType.RESEARCH_COMMENT: SqlResearchComment,
        }
        for output in outputs:
            try:
                model = entity_models[CanonicalEntityType(output.canonical_entity_type)]
            except ValueError, KeyError:
                raise ContributionConflict from None
            entity = session.get(model, output.canonical_entity_id)
            if (
                not isinstance(
                    entity,
                    (
                        SqlResearchObject,
                        SqlObjectRevision,
                        SqlRelationAssertion,
                        SqlResearchComment,
                    ),
                )
                or entity.ownership_scope_id != scope.id
                or output.ownership_scope_id != scope.id
            ):
                raise ContributionConflict
        links: list[SqlContributionEntityLink] = []
        for output in outputs:
            link = next(
                (
                    item
                    for item in session.scalars(
                        select(SqlContributionEntityLink).where(
                            SqlContributionEntityLink.envelope_id == envelope.id
                        )
                    )
                    if item.canonical_entity_id == output.canonical_entity_id
                    and item.canonical_entity_type == output.canonical_entity_type
                ),
                None,
            )
            if link is None:
                link = output_link(envelope.id, output)
                session.add(link)
            links.append(link)
        session.flush()
        receipt = SqlMutationReceipt(
            actor_key=actor_key,
            operation=operation,
            idempotency_key_digest=idempotency_digest,
            request_digest=request_digest,
            status=MutationReceiptStatus.COMMITTED,
            resource_ids=[str(envelope.id), *(str(link.id) for link in links)],
        )
        session.add(receipt)
        append_event(
            session,
            event_type="contribution.recorded",
            aggregate_type="contribution_envelope",
            aggregate_id=envelope.id,
            ownership_scope_id=ownership_scope_id,
            payload={
                "operation": operation,
                "envelope_id": str(envelope.id),
                "outputs": [
                    {
                        "entity_type": output.canonical_entity_type,
                        "entity_id": str(output.canonical_entity_id),
                    }
                    for output in outputs
                ],
            },
        )
        if commit:
            session.commit()
        else:
            session.flush()
    except Exception:
        session.rollback()
        raise
    return ContributionMutation(envelope, tuple(links), receipt, replayed=False)


def output_link(envelope_id: UUID, output: ContributionOutput) -> SqlContributionEntityLink:
    fields = {
        CanonicalEntityType.RESEARCH_OBJECT: "object_id",
        CanonicalEntityType.OBJECT_REVISION: "revision_id",
        CanonicalEntityType.RELATION_ASSERTION: "relation_id",
        CanonicalEntityType.RESEARCH_COMMENT: "comment_id",
    }
    return SqlContributionEntityLink(
        envelope_id=envelope_id,
        ownership_scope_id=output.ownership_scope_id,
        **{fields[CanonicalEntityType(output.canonical_entity_type)]: output.canonical_entity_id},
    )


def human_contribution(
    session: Session, *, user_id: UUID, scope_id: UUID, operation: str
) -> SqlContributionEnvelope:
    envelope = SqlContributionEnvelope(
        actor_kind=ContributionActorKind.HUMAN,
        human_user_id=user_id,
        ownership_scope_id=scope_id,
        operation=operation,
    )
    session.add(envelope)
    session.flush()
    return envelope


def actor_contribution(
    session: Session,
    *,
    actor: Actor,
    authority_user_id: UUID,
    scope_id: UUID,
    operation: str,
) -> SqlContributionEnvelope:
    """Create server-owned provenance for a non-receipted supporting entity."""

    scope = session.get(SqlResearchScope, scope_id)
    if scope is None:
        raise ContributionConflict
    if actor.kind is ActorKind.HUMAN:
        if actor.human_user_id != authority_user_id:
            raise ContributionConflict
    else:
        if actor.sponsor_user_id != authority_user_id:
            raise ContributionConflict
        if scope.project_id is None:
            from polycolab.access.authorization import require_public_participation

            require_public_participation(actor, ownership_scope_id=scope.id)
        else:
            require_project_write(actor, project_id=scope.project_id)
        if actor.ownership_scope_id != scope.id:
            raise ContributionConflict
    values = _envelope_values(actor)
    envelope = SqlContributionEnvelope(
        **values,
        ownership_scope_id=scope.id,
        operation=operation,
    )
    session.add(envelope)
    session.flush()
    return envelope


def link_output(
    session: Session,
    *,
    envelope: SqlContributionEnvelope,
    entity_type: CanonicalEntityType,
    entity_id: UUID,
    scope_id: UUID,
) -> None:
    session.add(output_link(envelope.id, ContributionOutput(entity_type, entity_id, scope_id)))
    append_event(
        session,
        event_type="research.created",
        aggregate_type=entity_type.value,
        aggregate_id=entity_id,
        ownership_scope_id=scope_id,
        payload={"schema_version": 1, "contribution_id": str(envelope.id)},
    )
