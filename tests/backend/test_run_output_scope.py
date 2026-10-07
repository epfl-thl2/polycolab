"""Authority requests cannot reinterpret private context or extend v1 agents."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_catalogue_api import admit, enable, headers
from test_library_api import attempt_payload

from polycolab.access.authorization import AuthorizationDenied
from polycolab.agents.grants import validate
from polycolab.agents.schemas import RunAuthorityRequest
from polycolab.agents.sessions import (
    RESEARCHER_VERSION_ID,
    ensure_platform_agent_versions,
    platform_agent_version,
)
from polycolab.entities.enums import PlatformAgentKind
from polycolab.research.objects import ResearchNotFound


def test_public_grant_requires_separate_public_task_and_public_inputs(client: TestClient) -> None:
    app = enable(client)
    entry = admit(client)
    project = client.post(
        "/api/v1/workspaces", headers=headers(), json={"visibility": "PRIVATE", "name": "Private"}
    ).json()
    user = client.get("/api/v1/users/me", headers=headers()).json()
    private = client.post(
        "/api/v1/objects",
        headers=headers(key="private"),
        json=attempt_payload(
            entry["object_version_id"],
            project_id=project["id"],
        ),
    ).json()
    private_version_id = next(
        item["entity_id"] for item in private["outputs"] if item["entity_type"] == "OBJECT_VERSION"
    )
    with pytest.raises(ValidationError):
        RunAuthorityRequest(
            destination="PUBLIC", public_target_revision_ids=[UUID(entry["object_version_id"])]
        )
    authority = RunAuthorityRequest(
        destination="PUBLIC",
        public_target_revision_ids=[UUID(entry["object_version_id"])],
        public_task_md="Explore this public statement",
        allowed_operations=["CREATE_RECORD"],
    )
    with app.state.session_factory() as db:
        ensure_platform_agent_versions(db)

        def check(version_id: UUID, ids: list[UUID]) -> None:
            validate(
                db,
                project_id=UUID(project["id"]),
                user_id=UUID(user["id"]),
                authority=authority,
                agent_version_id=version_id,
                context_ids=ids,
            )

        with pytest.raises(AuthorizationDenied):
            check(RESEARCHER_VERSION_ID, [UUID(entry["object_version_id"])])
        version = platform_agent_version(db, agent_kind=PlatformAgentKind.RESEARCHER, version=2)
        check(version.id, [UUID(entry["object_version_id"])])
        with pytest.raises(ResearchNotFound):
            check(version.id, [UUID(entry["object_version_id"]), UUID(private_version_id)])
        with pytest.raises(AuthorizationDenied):
            check(version.id, [])
