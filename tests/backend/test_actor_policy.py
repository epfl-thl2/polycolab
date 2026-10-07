from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from polycolab.access.actors import Actor, ActorKind, ActorOperation, agent_actor, human_actor
from polycolab.access.authorization import (
    AuthorizationDenied,
    require_catalogue_admission,
    require_catalogue_edit,
    require_catalogue_promotion,
    require_contribution_creation,
    require_contribution_edit,
    require_manage_credentials,
    require_manage_members,
    require_moderation,
    require_proposal_review,
    require_public_participation,
    require_publication,
    require_workspace_management,
    require_workspace_write,
)
from polycolab.accounts.authentication import Principal, human_actor_from_verified_principal
from polycolab.db.models import SqlUser
from polycolab.entities.enums import ResearchObjectKind
from polycolab.research.objects import create_object


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
        require_catalogue_admission,
        require_catalogue_promotion,
        require_catalogue_edit,
        require_publication,
        require_workspace_management,
        require_manage_members,
        require_manage_credentials,
        require_moderation,
        require_proposal_review,
    ],
)
def test_agent_never_inherits_human_only_authority(
    guard: Callable[[Actor], None],
) -> None:
    agent = delegated_agent(
        ActorOperation.CATALOGUE_ADMISSION,
        ActorOperation.CATALOGUE_PROMOTION,
        ActorOperation.CATALOGUE_EDIT,
        ActorOperation.PUBLICATION,
        ActorOperation.MANAGE_MEMBERS,
        ActorOperation.MANAGE_CREDENTIALS,
        ActorOperation.MODERATION,
        ActorOperation.PROPOSAL_REVIEW,
    )
    with pytest.raises(AuthorizationDenied):
        guard(agent)


def test_scoped_agent_operations_require_the_granted_operation_and_project() -> None:
    project_id = uuid4()
    agent = delegated_agent(ActorOperation.WORKSPACE_WRITE, project_id=project_id)
    require_workspace_write(agent, project_id=project_id)

    with pytest.raises(AuthorizationDenied):
        require_workspace_write(agent, project_id=uuid4())
    with pytest.raises(AuthorizationDenied):
        require_contribution_creation(agent, project_id=project_id)
    with pytest.raises(AuthorizationDenied):
        require_contribution_edit(agent, project_id=project_id)
    with pytest.raises(AuthorizationDenied):
        require_public_participation(agent, project_id=project_id)


def test_public_and_edit_grants_are_scoped_independently() -> None:
    project_id = uuid4()
    public_agent = delegated_agent(
        ActorOperation.CONTRIBUTION_CREATE,
        ActorOperation.PUBLIC_PARTICIPATION,
        project_id=project_id,
    )
    require_contribution_creation(public_agent, project_id=project_id)
    require_public_participation(public_agent, project_id=project_id)
    with pytest.raises(AuthorizationDenied):
        require_contribution_edit(public_agent, project_id=project_id)


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
        "/api/v1/workspaces",
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


def test_shared_research_writer_rejects_a_delegated_actor(client: TestClient) -> None:
    app = cast(Any, client.app)
    session = app.state.session_factory()
    try:
        with pytest.raises(AuthorizationDenied):
            create_object(
                session,
                project_id=uuid4(),
                kind=ResearchObjectKind.CLAIM,
                title="agent cannot write here",
                content_md="content",
                rationale=None,
                author=SqlUser(
                    issuer="https://issuer.example",
                    subject="sponsor",
                ),
                actor=delegated_agent(ActorOperation.WORKSPACE_WRITE),
            )
    finally:
        session.close()
