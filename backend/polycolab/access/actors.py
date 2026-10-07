"""Trusted actor values shared by human and hosted-agent authorization."""

from __future__ import annotations

from uuid import UUID

from polycolab.entities.access import Actor as Actor
from polycolab.entities.access import ActorKind as ActorKind
from polycolab.entities.access import ActorOperation as ActorOperation


def human_actor(user_id: UUID) -> Actor:
    return Actor(kind=ActorKind.HUMAN, human_user_id=user_id)


def agent_actor(
    *,
    sponsor_user_id: UUID,
    agent_version_id: UUID,
    run_id: UUID,
    capability_id: UUID,
    session_id: UUID,
    context_manifest_id: UUID,
    project_id: UUID,
    operation_scope: frozenset[ActorOperation],
    ownership_scope_id: UUID | None = None,
) -> Actor:
    return Actor(
        kind=ActorKind.AGENT,
        sponsor_user_id=sponsor_user_id,
        agent_version_id=agent_version_id,
        run_id=run_id,
        capability_id=capability_id,
        session_id=session_id,
        context_manifest_id=context_manifest_id,
        project_id=project_id,
        ownership_scope_id=ownership_scope_id,
        operation_scope=operation_scope,
    )


def external_agent_actor(
    *,
    sponsor_user_id: UUID,
    credential_id: UUID,
    run_id: UUID,
    project_id: UUID,
    ownership_scope_id: UUID,
    operation_scope: frozenset[ActorOperation],
) -> Actor:
    return Actor(
        kind=ActorKind.AGENT,
        sponsor_user_id=sponsor_user_id,
        external_credential_id=credential_id,
        external_run_id=run_id,
        project_id=project_id,
        ownership_scope_id=ownership_scope_id,
        operation_scope=operation_scope,
    )
