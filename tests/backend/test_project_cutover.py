"""Clean project contract plus explicitly bounded historical compatibility."""

from copy import deepcopy
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_catalogue_api import admit, headers
from test_direct_contributions import active_run
from test_shared_agent_api import body, setup

from polycolab.agents.grants import requested
from polycolab.db.models import (
    SqlMembership,
    SqlMutationReceipt,
    SqlResearchScope,
    SqlRunWriteGrant,
)
from polycolab.platform.config import Settings
from polycolab.platform.outbox import canonical_digest


@pytest.mark.parametrize(
    "path", ["/workspaces", "/workspaces/demo", "/workspaces/id/objects/x", "/demo/workspaces/id"]
)
def test_browser_bookmarks_redirect_without_losing_query(client: TestClient, path: str) -> None:
    response = client.get(path + "?scope=member&revision=123", follow_redirects=False)
    assert response.status_code == 308
    assert (
        response.headers["location"]
        == path.replace("workspaces", "projects") + "?scope=member&revision=123"
    )


def test_clean_contract_rejects_obsolete_routes_and_inputs(client: TestClient) -> None:
    schema = cast(Any, client.app).openapi()
    assert not any("workspace" in path for path in schema["paths"])
    operations = [
        operation["operationId"] for item in schema["paths"].values() for operation in item.values()
    ]
    assert len(operations) == len(set(operations))
    for path in (
        "workspaces",
        "workspace-copies",
        "workspace-references",
        "activity/workspaces",
        "workspaces/11111111-1111-4111-8111-111111111111/repository",
        "workspaces/11111111-1111-4111-8111-111111111111/tasks",
        "workspaces/11111111-1111-4111-8111-111111111111/worktrees",
        "workspaces/11111111-1111-4111-8111-111111111111/members",
    ):
        assert client.get(f"/api/v1/{path}", headers=headers()).status_code == 404
    for path in ("activity", "search", "projects", "artifacts"):
        assert (
            client.get(f"/api/v1/{path}?workspace_id=obsolete", headers=headers()).status_code
            == 422
        )
    entry = admit(client)
    assert (
        client.post(
            "/api/v1/project-copies",
            headers=headers(),
            json={
                "source_object_version_id": entry["object_version_id"],
                "workspace_name": "obsolete",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/project-references",
            headers=headers(),
            json={
                "object_version_id": entry["object_version_id"],
                "create_new_workspace": True,
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/objects",
            headers=headers(),
            json={
                **body(str(UUID(int=1))),
                "destination": {"kind": "workspace", "workspace_id": str(UUID(int=1))},
            },
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "name,value",
    [
        ("HOSTED_AGENT_PROJECT_CAPACITY", "3"),
        ("PROJECT_REPOSITORY_DIRECTORY", "/private/tmp/project-repositories"),
        ("PROJECT_REPOSITORY_MAX_BYTES", "2097152"),
        ("PUBLIC_PROJECT_MODERATOR_SUBJECTS", '["moderator"]'),
        ("VERIFICATION_PROJECT_CONCURRENT_JOBS", "11"),
        ("VERIFICATION_PROJECT_DAILY_CPU_SECONDS", "234"),
        ("VERIFICATION_PROJECT_DAILY_MEMORY_BYTE_SECONDS", "456"),
    ],
)
def test_old_environment_fallback_and_new_precedence(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    old = name.replace("PROJECT", "WORKSPACE")
    monkeypatch.setenv(old, value)
    historical = getattr(Settings(), name.lower())
    monkeypatch.delenv(old)
    monkeypatch.setenv(name, value)
    assert getattr(Settings(), name.lower()) == historical
    monkeypatch.setenv(
        old,
        '["other"]'
        if "SUBJECTS" in old
        else "/private/tmp/old-repos"
        if "DIRECTORY" in old
        else "1",
    )
    assert getattr(Settings(), name.lower()) == historical


def test_historical_direct_receipt_replays_and_rechecks_authority(client: TestClient) -> None:
    project, secret = setup(client)
    current = body(project["id"])
    first = client.post("/api/v1/objects", headers=headers(secret, "historical"), json=current)
    assert first.status_code == 201, first.text
    app = cast(Any, client.app)
    from polycolab.research.version_schemas import VersionedObjectCreate

    historical = VersionedObjectCreate.model_validate(current).model_dump(mode="json")
    historical["destination"] = {"kind": "workspace", "workspace_id": project["id"]}
    with app.state.session_factory() as session:
        scope = session.scalar(
            select(SqlResearchScope).where(SqlResearchScope.project_id == UUID(project["id"]))
        )
        receipt = session.scalar(
            select(SqlMutationReceipt).where(SqlMutationReceipt.operation == "direct.object.create")
        )
        assert receipt.request_digest == canonical_digest(
            {
                "version": 1,
                "payload": {
                    "destination_scope_id": str(scope.id),
                    "payload": historical,
                },
            }
        )
        saved_digest = receipt.request_digest
    replay = client.post("/api/v1/objects", headers=headers(secret, "historical"), json=current)
    assert replay.status_code == 201 and replay.json()["replayed"] is True
    assert replay.json()["outputs"] == first.json()["outputs"]
    altered = deepcopy(current)
    altered["snapshot"]["content"]["content_md"] = "Changed workspace text stays literal"
    assert (
        client.post(
            "/api/v1/objects", headers=headers(secret, "historical"), json=altered
        ).status_code
        == 409
    )
    with app.state.session_factory() as session:
        membership = session.scalar(
            select(SqlMembership).where(SqlMembership.project_id == UUID(project["id"]))
        )
        session.delete(membership)
        session.commit()
    assert client.post(
        "/api/v1/objects", headers=headers(secret, "historical"), json=current
    ).status_code in {403, 404}
    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(SqlMutationReceipt).where(
                    SqlMutationReceipt.operation == "direct.object.create"
                )
            ).request_digest
            == saved_digest
        )


def test_historical_grant_digest_is_checked_before_projection(client: TestClient) -> None:
    app, _, run_id, _, _ = active_run(client, public=False)
    with app.state.session_factory() as session:
        grant = session.get(SqlRunWriteGrant, run_id)
        legacy = {**grant.request, "destination": "WORKSPACE"}
        grant.request = legacy
        grant.request_digest = canonical_digest(legacy)
        session.commit()
        authority = requested(session, run_id)
        assert authority is not None and authority.destination == "PROJECT"
        assert grant.request == legacy
        assert grant.request_digest == canonical_digest(legacy)
        grant.request_digest = "0" * 64
        from polycolab.access.authorization import AuthorizationDenied

        with pytest.raises(AuthorizationDenied):
            requested(session, run_id)


def test_historical_credential_rights_project_without_rewriting(client: TestClient) -> None:
    from polycolab.db.models import SqlExternalAgentCredential

    _, secret = setup(client)
    app = cast(Any, client.app)
    with app.state.session_factory() as session:
        credential = session.scalar(select(SqlExternalAgentCredential))
        legacy = [
            value.replace("PROJECT_WRITE", "WORKSPACE_WRITE") for value in credential.fixed_rights
        ]
        credential.fixed_rights = legacy
        session.commit()
        credential_id = credential.id
    identity = client.get("/api/v1/me", headers=headers(secret))
    assert identity.status_code == 200
    assert "PROJECT_WRITE" in identity.json()["fixed_rights"]
    listed = client.get("/api/v1/account/agent-keys", headers=headers()).json()["items"]
    assert listed[0]["fixed_rights"] == identity.json()["fixed_rights"]
    with app.state.session_factory() as session:
        assert session.get(SqlExternalAgentCredential, credential_id).fixed_rights == legacy
    assert (
        client.delete(f"/api/v1/account/agent-keys/{credential_id}", headers=headers()).status_code
        == 204
    )
    assert client.get("/api/v1/me", headers=headers(secret)).status_code == 401


def test_historical_copy_receipt_and_default_survive_rename(client: TestClient) -> None:
    entry = admit(client)
    payload = {"source_object_version_id": entry["object_version_id"]}
    first = client.post("/api/v1/project-copies", headers=headers(key="old-copy"), json=payload)
    assert first.status_code == 201, first.text
    project_id = first.json()["project_id"]
    assert (
        client.get(f"/api/v1/projects/{project_id}", headers=headers()).json()["name"]
        == "Research project"
    )
    with cast(Any, client.app).state.session_factory() as session:
        receipt = session.scalar(
            select(SqlMutationReceipt).where(SqlMutationReceipt.operation == "workspace.copy")
        )
        assert receipt is not None
        assert receipt.request_digest == canonical_digest(
            {
                "version": 1,
                "payload": {
                    "revision_id": entry["object_version_id"],
                    "project_id": None,
                    "workspace_name": "Research workspace",
                    "workspace_visibility": "PUBLIC",
                },
            }
        )
    assert (
        client.post("/api/v1/project-copies", headers=headers(key="old-copy"), json=payload).json()
        == first.json()
    )
    assert (
        client.post(
            "/api/v1/project-copies",
            headers=headers(key="old-copy"),
            json={
                **payload,
                "project_name": "Changed",
            },
        ).status_code
        == 409
    )
