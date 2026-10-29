from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from polycolab.access.actors import (
    Actor,
    ActorKind,
    ActorOperation,
    agent_actor,
    human_actor,
)
from polycolab.access.authorization import (
    AuthorizationDenied,
    require_manage_credentials,
    require_manage_members,
    require_moderation,
    require_project_management,
    require_project_write,
)
from polycolab.accounts.authentication import (
    Principal,
    human_actor_from_verified_principal,
)


def delegated_agent(*operations: ActorOperation, project_id: UUID | None = None) -> Actor:
    return agent_actor(
        sponsor_user_id=uuid4(),
        agent_version_id=uuid4(),
        run_id=uuid4(),
        capability_id=uuid4(),
        session_id=uuid4(),
        context_manifest_id=uuid4(),
        project_id=project_id or uuid4(),
        operation_scope=frozenset(operations),
    )


@pytest.mark.parametrize(
    "guard",
    [
        require_project_management,
        require_manage_members,
        require_manage_credentials,
        require_moderation,
    ],
)
def test_agent_never_inherits_human_only_authority(
    guard: Callable[[Actor], None],
) -> None:
    agent = delegated_agent(
        ActorOperation.MANAGE_MEMBERS,
        ActorOperation.MANAGE_CREDENTIALS,
        ActorOperation.MODERATION,
    )
    with pytest.raises(AuthorizationDenied):
        guard(agent)


def test_scoped_agent_operations_require_the_granted_operation_and_project() -> None:
    project_id = uuid4()
    agent = delegated_agent(ActorOperation.PROJECT_WRITE, project_id=project_id)
    require_project_write(agent, project_id=project_id)

    with pytest.raises(AuthorizationDenied):
        require_project_write(agent, project_id=uuid4())
    with pytest.raises(AuthorizationDenied):
        require_project_write(delegated_agent(), project_id=project_id)


def test_human_actor_is_constructed_from_verified_identity_only() -> None:
    user_id = uuid4()
    actor = human_actor_from_verified_principal(
        principal=Principal("issuer", "subject"), user_id=user_id
    )
    assert actor == human_actor(user_id)
    assert actor.kind is ActorKind.HUMAN

    with pytest.raises(ValueError):
        Actor(kind=ActorKind.HUMAN, human_user_id=user_id, sponsor_user_id=uuid4())


def test_request_actor_kind_is_rejected_at_http_boundaries(client: TestClient) -> None:
    project = client.post(
        "/api/v1/projects",
        headers={"Authorization": "Bearer owner"},
        json={"visibility": "PRIVATE", "name": "authority", "actor_kind": "AGENT"},
    )
    assert project.status_code == 422

    tool = client.post(
        "/internal/v1/tools/call",
        headers={"Authorization": "Bearer capability"},
        json={"name": "get_context", "actor_kind": "AGENT"},
    )
    assert tool.status_code == 422
