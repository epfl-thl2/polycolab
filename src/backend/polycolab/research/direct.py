"""Per-write authority and receipts for humans and stable external agents."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_serializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor, ActorKind, ActorOperation, human_actor
from polycolab.access.authorization import (
    AuthorizationDenied,
    ProjectAction,
    lock_project_authorization,
    project_policy,
)
from polycolab.agents.external import ExternalAgentInvalid, ExternalAgentLimit, _aware
from polycolab.app.access import ResearchAccess
from polycolab.app.schemas import ApiModel, RequestModel
from polycolab.catalogue.admission import lock_commons
from polycolab.db.models import (
    SqlCatalogueRevision,
    SqlContributionEnvelope,
    SqlExternalAgentCredential,
    SqlResearchObject,
    SqlResearchScope,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.platform import mutation_keys
from polycolab.research.contributions import _envelope_values
from polycolab.research.objects import ResearchNotFound
from polycolab.research.records import public_revision


class ProjectDestination(RequestModel):
    kind: Literal["project"]
    project_id: UUID


class LibraryDestination(RequestModel):
    kind: Literal["library"]
    statement_revision_id: UUID


Destination = Annotated[ProjectDestination | LibraryDestination, Field(discriminator="kind")]


class OutputRead(ApiModel):
    entity_type: str
    entity_id: UUID

    @field_serializer("entity_type")
    def current_entity_type(self, value: str) -> str:
        """Project stored canonical labels without rewriting receipt identities."""
        return {
            "OBJECT_REVISION": "OBJECT_VERSION",
            "RELATION_ASSERTION": "OBJECT_VERSION_RELATIONSHIP",
        }.get(value, value)


class MutationResult(ApiModel):
    contribution_id: UUID
    outputs: list[OutputRead]
    replayed: bool


def destination_scope(session: Session, destination: Destination) -> SqlResearchScope:
    if isinstance(destination, ProjectDestination):
        scope = session.scalar(
            select(SqlResearchScope).where(SqlResearchScope.project_id == destination.project_id)
        )
        if scope is None:
            raise ResearchNotFound
        return scope
    revision = public_revision(session, destination.statement_revision_id)
    if not session.scalar(
        select(SqlCatalogueRevision.entry_id).where(SqlCatalogueRevision.revision_id == revision.id)
    ):
        raise ResearchNotFound
    return lock_commons(session)


def authorize(session: Session, access: ResearchAccess, scope: SqlResearchScope) -> Actor:
    user_id = access.require_user_id()
    if scope.project_id is not None:
        lock_project_authorization(
            SqlAlchemyTransaction(session), project_id=scope.project_id, user_id=user_id
        )
        project_policy.require_scope(
            SqlAlchemyTransaction(session),
            scope.project_id,
            user_id,
            ProjectAction.CREATE_RESEARCH,
        )
    else:
        lock_commons(session)
    if access.credential is None:
        return human_actor(user_id)
    credential = session.scalar(
        select(SqlExternalAgentCredential)
        .where(SqlExternalAgentCredential.id == access.credential.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        credential is None
        or credential.agent_id is None
        or credential.revoked_at is not None
        or _aware(credential.expires_at) <= datetime.now(UTC)
    ):
        raise ExternalAgentInvalid
    if scope.project_id is None and not credential.allow_library_contributions:
        raise AuthorizationDenied("key does not permit Library contributions")
    return Actor(
        kind=ActorKind.AGENT,
        sponsor_user_id=user_id,
        project_id=scope.project_id,
        ownership_scope_id=scope.id,
        external_credential_id=credential.id,
        external_agent_id=credential.agent_id,
        operation_scope=frozenset(
            {
                *({ActorOperation.REVIEW_RESEARCH} if credential.allow_reviews else set()),
                ActorOperation.CONTRIBUTION_CREATE,
                ActorOperation.CONTRIBUTION_EDIT,
                ActorOperation.PUBLIC_PARTICIPATION
                if scope.project_id is None
                else ActorOperation.PROJECT_WRITE,
            }
        ),
    )


def require_edit_author(session: Session, actor: Actor, obj: SqlResearchObject) -> None:
    from polycolab.db.models import SqlCatalogueEntry

    if session.get(SqlCatalogueEntry, obj.id):
        raise AuthorizationDenied("official Library revisions require catalogue authority")
    if actor.kind == ActorKind.HUMAN:
        if obj.created_by_user_id != actor.human_user_id:
            raise AuthorizationDenied("only the author may revise this contribution")
    else:
        envelope = (
            session.get(SqlContributionEnvelope, obj.contribution_id)
            if obj.contribution_id
            else None
        )
        identity = envelope.external_agent_id if envelope else None
        if envelope and identity is None and envelope.external_credential_id:
            credential = session.get(SqlExternalAgentCredential, envelope.external_credential_id)
            identity = credential.agent_id if credential else None
        if identity != actor.external_agent_id:
            raise AuthorizationDenied("only the authoring agent may revise this contribution")


def mutate(
    session: Session,
    access: ResearchAccess,
    scope: SqlResearchScope,
    operation: str,
    key: str,
    payload: object,
    apply: Callable[[Actor, SqlContributionEnvelope], list[OutputRead]],
) -> MutationResult:
    operation = f"direct.{operation}"
    actor = authorize(session, access, scope)
    actor_key = (
        f"agent:{actor.external_agent_id}"
        if actor.kind == ActorKind.AGENT
        else f"human:{actor.human_user_id}"
    )
    request = {"destination_scope_id": str(scope.id), "payload": payload}
    mutation_keys.lock_key(session, actor_key, operation, key)
    receipt = mutation_keys.receipt(session, actor_key, operation, key, request)
    if receipt:
        envelope = session.get(SqlContributionEnvelope, UUID(receipt.resource_ids[0]))
        if envelope is None:
            raise ResearchNotFound
        outputs = [
            OutputRead(entity_type=value.split(":", 1)[0], entity_id=UUID(value.split(":", 1)[1]))
            for value in receipt.resource_ids[1:]
        ]
        return MutationResult(contribution_id=envelope.id, outputs=outputs, replayed=True)
    if access.credential and access.credential.mutation_count >= access.credential.max_mutations:
        raise ExternalAgentLimit("credential_mutation_budget_exhausted")
    envelope = SqlContributionEnvelope(
        **_envelope_values(actor), ownership_scope_id=scope.id, operation=operation
    )
    session.add(envelope)
    session.flush()
    outputs = apply(actor, envelope)
    from polycolab.db.models import MutationReceiptStatus, SqlMutationReceipt
    from polycolab.platform.outbox import canonical_digest
    from polycolab.platform.project_history import receipt_payload

    session.add(
        SqlMutationReceipt(
            actor_key=actor_key,
            operation=operation,
            idempotency_key_digest=canonical_digest(key),
            request_digest=canonical_digest(
                {"version": 1, "payload": receipt_payload(operation, request)}
            ),
            status=MutationReceiptStatus.COMMITTED,
            resource_ids=[
                str(envelope.id),
                *[f"{output.entity_type}:{output.entity_id}" for output in outputs],
            ],
        )
    )
    if access.credential:
        access.credential.mutation_count += 1
    session.commit()
    return MutationResult(contribution_id=envelope.id, outputs=outputs, replayed=False)
