from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from research_requests import post_research
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from polycolab.agents.external import fixed_right_values
from polycolab.artifacts.storage import GarageStorage
from polycolab.db.models import (
    SqlArtifact,
    SqlAuthSession,
    SqlExternalAgentCredential,
    SqlExternalResearchRun,
    SqlLocalAccount,
    SqlOperatorRestoreInvalidation,
    SqlProject,
    SqlResearchActivityEvent,
    SqlUser,
)
from polycolab.entities.enums import WorkspaceVisibility
from polycolab.entities.time import utc_now
from polycolab.operations.account_recovery import OperatorRecoveryInvalid, recover_account
from polycolab.operations.restore_invalidation import (
    RestoreInvalidationInvalid,
    invalidate_restored_protected_access,
)
from polycolab.operations.restore_invalidation import (
    main as restore_invalidation_main,
)


def headers(token: str = "owner") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs: Any) -> None:
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        data = self.objects[kwargs["Key"]]
        return {"Body": BytesIO(data), "ContentLength": len(data)}

    def delete_object(self, **kwargs: Any) -> None:
        self.objects.pop(kwargs["Key"], None)


def enable_research(client: TestClient, *, artifacts: bool = False) -> None:
    app = cast(Any, client.app)
    app.state.settings.public_workspace_moderator_subjects = ["owner"]
    app.state.settings.external_agent_max_requests = 10_000
    app.state.settings.external_agent_max_mutations = 1_000
    if artifacts:
        app.state.artifact_storage = GarageStorage(MemoryS3(), "research-test")


def create_workspace(client: TestClient, name: str = "Public research") -> dict[str, Any]:
    response = client.post("/api/v1/workspaces", headers=headers(), json={"name": name})
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def version_snapshot(kind: str, title: str, content: str) -> dict[str, Any]:
    return {
        "kind": {
            "CLAIM": "STATEMENT",
            "PROOF_SKETCH": "PROOF",
            "IDEA": "NOTE",
            "DISCUSSION": "NOTE",
            "COUNTEREXAMPLE": "NOTE",
            "COMPUTATION": "NOTE",
        }.get(kind, kind),
        "content": {
            "title": title,
            "content_md": content,
            "assumptions_md": "None",
            "reported_outcome": None,
            "explanation_md": None,
        },
        "structural_relationships": [],
        "change_summary": None,
    }


def create_human_claim(client: TestClient, project_id: str, title: str) -> dict[str, Any]:
    response = post_research(
        client,
        "/api/v1/objects",
        headers=headers(),
        json={
            "destination": {"kind": "workspace", "workspace_id": project_id},
            "snapshot": version_snapshot("CLAIM", title, f"Content: {title}"),
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def issue(client: TestClient, project_id: str, token: str = "owner") -> dict[str, Any]:
    identity = client.post(
        "/api/v1/account/agents", headers=headers(token), json={"name": "Local theorem agent"}
    )
    assert identity.status_code == 201
    response = client.post(
        "/api/v1/account/agent-keys",
        headers=headers(token),
        json={"name": "Local theorem agent", "agent_id": identity.json()["id"]},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_public_contract_and_external_retry_revocation(client: TestClient) -> None:
    enable_research(client)
    project = create_workspace(client)
    credential = issue(client, project["id"])
    payload = {
        "destination": {"kind": "workspace", "workspace_id": project["id"]},
        "snapshot": version_snapshot("CLAIM", "Independent claim", "Content"),
    }
    auth = {**headers(credential["secret"]), "Idempotency-Key": "claim"}
    first = client.post("/api/v1/objects", headers=auth, json=payload)
    assert first.status_code == 201, first.text
    replay = client.post("/api/v1/objects", headers=auth, json=payload)
    assert replay.json() == {**first.json(), "replayed": True}
    revision = first.json()["outputs"][1]["entity_id"]
    assert client.get(f"/api/v1/versions/{revision}").status_code == 200
    assert (
        client.get(f"/api/v1/agent-profiles/{credential['agent_id']}").json()[
            "authored_contributions"
        ]
        == 1
    )
    assert (
        client.delete(
            f"/api/v1/account/agent-keys/{credential['id']}", headers=headers()
        ).status_code
        == 204
    )
    assert client.post("/api/v1/objects", headers=auth, json=payload).status_code == 401
    assert client.get(f"/api/v1/versions/{revision}").status_code == 200


def test_external_exact_public_input_relation_scope_and_stale_edit(client: TestClient) -> None:
    enable_research(client)
    project = create_workspace(client)
    other = create_workspace(client, "Public source")
    source = create_human_claim(client, other["id"], "Exact public source")
    credential = issue(client, project["id"])
    auth = {**headers(credential["secret"]), "Idempotency-Key": "claim"}
    result = client.post(
        "/api/v1/objects",
        headers=auth,
        json={
            "destination": {"kind": "workspace", "workspace_id": project["id"]},
            "snapshot": version_snapshot("CLAIM", "My claim", "x"),
        },
    ).json()
    object_id, revision_id = [row["entity_id"] for row in result["outputs"]]
    relation = client.post(
        "/api/v1/relations",
        headers=auth,
        json={
            "destination": {"kind": "workspace", "workspace_id": project["id"]},
            "direction": "UNIDIRECTIONAL",
            "source_object_version_id": revision_id,
            "target_object_version_id": source["current_object_version_id"],
            "relationship_type": "DEPENDS_ON",
            "description": "Exact source",
        },
    )
    assert relation.status_code == 201, relation.text
    edit = {
        "expected_current_object_version_id": revision_id,
        "snapshot": version_snapshot("CLAIM", "Revised", "y"),
    }
    path = f"/api/v1/objects/{object_id}/versions"
    revised = client.post(path, headers=auth, json=edit)
    assert revised.status_code == 201, revised.text
    assert (
        client.post(path, headers={**auth, "Idempotency-Key": "stale"}, json=edit).status_code
        == 409
    )
    other_key = issue(client, project["id"])
    assert (
        client.post(
            path, headers={**headers(other_key["secret"]), "Idempotency-Key": "other"}, json=edit
        ).status_code
        == 403
    )
    assert client.get(f"/api/v1/versions/{revision_id}").json()["content"]["content_md"] == "x"


def test_external_artifact_becomes_public_only_after_attachment(client: TestClient) -> None:
    enable_research(client, artifacts=True)
    project = create_workspace(client)
    target = create_human_claim(client, project["id"], "Evidence target")
    credential = issue(client, project["id"])
    auth = {**headers(credential["secret"]), "Idempotency-Key": "evidence"}
    upload = client.post(
        "/api/v1/artifacts",
        headers=auth,
        params={
            "workspace_id": project["id"],
            "sha256": hashlib.sha256(b"abc").hexdigest(),
            "byte_length": 3,
        },
        content=b"abc",
    )
    assert upload.status_code == 201, upload.text
    artifact = upload.json()["id"]
    assert client.get(f"/api/v1/artifacts/{artifact}").status_code == 404
    attached = client.post(
        "/api/v1/attachments",
        headers=auth,
        json={
            "artifact_id": artifact,
            "object_version_id": target["current_object_version_id"],
            "role": "EVIDENCE",
        },
    )
    assert attached.status_code == 200, attached.text
    assert client.get(f"/api/v1/artifacts/{artifact}/content").content == b"abc"
    receipt = client.get(f"/api/v1/contributions/{attached.json()['contribution_id']}")
    assert receipt.status_code == 200
    assert receipt.json()["outputs"] == attached.json()["outputs"]
    public_urls = [
        f"/api/v1/artifacts/{artifact}",
        f"/api/v1/artifacts/{artifact}/content",
        f"/api/v1/contributions/{attached.json()['contribution_id']}",
    ]
    for visibility, status in [("PRIVATE", 404), ("PUBLIC", 200)]:
        assert (
            client.patch(
                f"/api/v1/workspaces/{project['id']}",
                headers=headers(),
                json={"visibility": visibility},
            ).status_code
            == 200
        )
        for url in public_urls:
            assert client.get(url).status_code == status
            assert client.get(url, headers=headers()).status_code == 200


def test_interrupted_external_upload_is_private_and_safely_retryable(client: TestClient) -> None:
    enable_research(client, artifacts=True)
    project = create_workspace(client)
    credential = issue(client, project["id"])
    auth = {**headers(credential["secret"]), "Idempotency-Key": "upload"}
    params = {
        "workspace_id": project["id"],
        "sha256": hashlib.sha256(b"abc").hexdigest(),
        "byte_length": 3,
    }
    assert (
        client.post("/api/v1/artifacts", headers=auth, params=params, content=b"a").status_code
        == 422
    )
    with cast(Any, client.app).state.session_factory() as session:
        assert session.query(SqlArtifact).count() == 0
    response = client.post("/api/v1/artifacts", headers=auth, params=params, content=b"abc")
    assert response.status_code == 201, response.text
    assert (
        client.post("/api/v1/artifacts", headers=auth, params=params, content=b"abc").json()["id"]
        == response.json()["id"]
    )
    assert client.get(f"/api/v1/artifacts/{response.json()['id']}").status_code == 404


def test_public_workspace_moderation_and_lifecycle_filter_every_projection(
    client: TestClient,
) -> None:
    enable_research(client)
    project = create_workspace(client, "Moderation")
    target = create_human_claim(client, project["id"], "Moderate me")
    source = create_human_claim(client, project["id"], "Relation source")
    relation = client.post(
        "/api/v1/relations",
        headers={**headers(), "Idempotency-Key": "relation"},
        json={
            "destination": {"kind": "workspace", "workspace_id": project["id"]},
            "direction": "UNIDIRECTIONAL",
            "source_object_version_id": source["current_object_version_id"],
            "target_object_version_id": target["current_object_version_id"],
            "relationship_type": "DEPENDS_ON",
            "description": "Exact source",
        },
    )
    assert relation.status_code == 201, relation.text
    url = f"/api/v1/operator/workspaces/{project['id']}/objects/{target['id']}/moderation"
    hidden = client.post(
        url,
        headers={**headers(), "Idempotency-Key": "hide"},
        json={
            "expected_current_object_version_id": target["current_object_version_id"],
            "hidden": True,
            "reason": "Withdraw",
        },
    )
    assert hidden.status_code == 200, hidden.text
    assert client.get(f"/api/v1/versions/{target['current_object_version_id']}").status_code == 404
    public = client.get("/api/v1/activity", params={"workspace_id": project["id"]})
    assert public.status_code == 200, public.text
    assert all(
        row["object_id"] != target["id"] and row["action"] != "relation.created"
        for row in public.json()["items"]
    )
    assert (
        client.delete(f"/api/v1/workspaces/{project['id']}", headers=headers()).status_code == 204
    )
    assert (
        client.get("/api/v1/activity", params={"workspace_id": project["id"]}).json()["items"] == []
    )


def test_external_limits_expiry_and_membership_loss_are_live(client: TestClient) -> None:
    enable_research(client)
    app = cast(Any, client.app)
    app.state.settings.external_agent_max_mutations = 1
    project = create_workspace(client)
    credential = issue(client, project["id"])
    auth = {**headers(credential["secret"]), "Idempotency-Key": "one"}
    payload = {
        "destination": {"kind": "workspace", "workspace_id": project["id"]},
        "snapshot": version_snapshot("NOTE", "Note", "x"),
    }
    assert client.post("/api/v1/objects", headers=auth, json=payload).status_code == 201
    assert (
        client.post(
            "/api/v1/objects", headers={**auth, "Idempotency-Key": "two"}, json=payload
        ).status_code
        == 429
    )
    assert client.post("/api/v1/objects", headers=auth, json=payload).json()["replayed"] is True
    ttl = app.state.settings.external_agent_credential_ttl_seconds
    app.state.settings.external_agent_credential_ttl_seconds = -1
    try:
        expired = issue(client, project["id"])
    finally:
        app.state.settings.external_agent_credential_ttl_seconds = ttl
    assert client.get("/api/v1/me", headers=headers(expired["secret"])).status_code == 401


def test_external_credential_fixed_contract_and_request_limit(client: TestClient) -> None:
    enable_research(client)
    app = cast(Any, client.app)
    app.state.settings.external_agent_credential_ttl_seconds = 3600
    app.state.settings.external_agent_max_requests = 2
    project = create_workspace(client, "Fixed credential policy")
    attempted_broadening = client.post(
        "/api/v1/account/agent-keys",
        headers=headers(),
        json={
            "name": "Caller-selected policy",
            "expires_in_seconds": 31_536_000,
            "rights": ["MANAGE_MEMBERS"],
        },
    )
    assert attempted_broadening.status_code == 422

    credential = issue(client, project["id"])
    created_at = datetime.fromisoformat(credential["created_at"])
    expires_at = datetime.fromisoformat(credential["expires_at"])
    assert timedelta(seconds=3599) <= expires_at - created_at <= timedelta(seconds=3600)
    secret = credential["secret"]
    expected_rights = {
        "WORKSPACE_WRITE",
        "CONTRIBUTION_CREATE",
        "CONTRIBUTION_EDIT",
        "PUBLIC_PARTICIPATION",
    }
    assert set(credential["fixed_rights"]) == expected_rights
    first = client.get("/api/v1/me", headers=headers(secret))
    assert first.status_code == 200, first.text
    assert first.json()["credential_id"] == credential["id"]
    assert set(first.json()["fixed_rights"]) == expected_rights
    assert first.json()["requests_remaining"] == 2
    assert first.json()["mutations_remaining"] == 1000
    second = client.get("/api/v1/workspaces", headers=headers(secret))
    assert second.status_code == 200
    client.get("/api/v1/workspaces", headers=headers(secret))
    exhausted = client.get("/api/v1/workspaces", headers=headers(secret))
    assert exhausted.status_code == 429
    assert exhausted.json()["error"]["code"] == "credential_request_budget_exhausted"
    listed = client.get("/api/v1/account/agent-keys", headers=headers())
    assert listed.status_code == 200
    assert listed.json()["items"][0]["request_count"] == 2
    assert set(listed.json()["items"][0]["fixed_rights"]) == expected_rights
    assert "secret" not in listed.json()["items"][0]
    assert client.get(f"/api/v1/workspaces/{project['id']}").status_code == 200

    corrupted = issue(client, project["id"])
    with app.state.session_factory() as session:
        row = session.get(SqlExternalAgentCredential, UUID(corrupted["id"]))
        assert row is not None
        row.fixed_rights = ["WORKSPACE_WRITE"]
        if session.get_bind().dialect.name == "postgresql":
            with pytest.raises(DBAPIError, match="external agent credential grant is immutable"):
                session.commit()
            session.rollback()
        else:
            session.commit()
    checked = client.get("/api/v1/me", headers=headers(corrupted["secret"]))
    if app.state.engine.dialect.name == "postgresql":
        assert checked.status_code == 200
        assert set(checked.json()["fixed_rights"]) == expected_rights
    else:
        assert checked.status_code == 401
        assert checked.json()["error"]["code"] == "invalid_agent_credential"


def test_transition_and_operator_recovery_invalidate_protected_access(client: TestClient) -> None:
    app = cast(Any, client.app)
    project_id = client.post(
        "/api/v1/workspaces",
        headers=headers(),
        json={"name": "Private research", "visibility": "PRIVATE"},
    ).json()["id"]
    with app.state.session_factory() as session:
        project = session.get(SqlProject, UUID(project_id))
        assert project is not None
        assert project.visibility is WorkspaceVisibility.PRIVATE

        account = SqlLocalAccount(
            username="recovery-user",
            password_digest="old",
            display_name="Recovery User",
        )
        session.add(account)
        session.flush()
        user = SqlUser(
            issuer="polycolab-local",
            subject=str(account.id),
            display_name=account.display_name,
        )
        session.add(user)
        session.flush()
        auth_session = SqlAuthSession(
            account_id=account.id,
            token_digest="a" * 64,
            expires_at=utc_now() + timedelta(days=1),
        )
        credential = SqlExternalAgentCredential(
            scope_kind="WORKSPACE",
            project_id=project.id,
            sponsor_user_id=user.id,
            name="Delegated",
            token_digest="b" * 64,
            fixed_rights=fixed_right_values(),
            expires_at=utc_now() + timedelta(days=1),
            max_requests=10,
            max_mutations=10,
        )
        session.add_all([auth_session, credential])
        session.flush()
        run = SqlExternalResearchRun(
            credential_id=credential.id,
            project_id=project.id,
            sponsor_user_id=user.id,
            client_request_id=uuid4(),
            input_revision_ids=[],
        )
        session.add(run)
        session.commit()

        try:
            recover_account(
                session,
                account_id=account.id,
                exact_username="wrong-user",
                new_password="a sufficiently long replacement",
                verification_reference="support-case-123",
            )
            raise AssertionError("mismatched recovery must fail")
        except OperatorRecoveryInvalid:
            session.rollback()
        result = recover_account(
            session,
            account_id=account.id,
            exact_username="recovery-user",
            new_password="a sufficiently long replacement",
            verification_reference="support-case-123",
        )
        assert (result.revoked_sessions, result.revoked_credentials, result.revoked_runs) == (
            1,
            1,
            1,
        )
        assert session.get(SqlAuthSession, auth_session.id).revoked_at is not None
        assert session.get(SqlExternalAgentCredential, credential.id).revoked_at is not None
        assert session.get(SqlExternalResearchRun, run.id).status == "REVOKED"


def test_restore_invalidation_revokes_the_complete_protected_cohort(client: TestClient) -> None:
    app = cast(Any, client.app)
    project_id = create_workspace(client)["id"]
    with app.state.session_factory() as session:
        account = SqlLocalAccount(username="restored-user", password_digest="old")
        session.add(account)
        session.flush()
        user = SqlUser(issuer="polycolab-local", subject=str(account.id))
        session.add(user)
        session.flush()
        active_session = SqlAuthSession(
            account_id=account.id,
            token_digest="c" * 64,
            expires_at=utc_now() + timedelta(days=1),
        )
        already_revoked_session = SqlAuthSession(
            account_id=account.id,
            token_digest="d" * 64,
            expires_at=utc_now() + timedelta(days=1),
            revoked_at=utc_now(),
        )
        credential = SqlExternalAgentCredential(
            scope_kind="WORKSPACE",
            project_id=UUID(project_id),
            sponsor_user_id=user.id,
            name="Restored delegated agent",
            token_digest="e" * 64,
            fixed_rights=fixed_right_values(),
            expires_at=utc_now() + timedelta(days=1),
            max_requests=10,
            max_mutations=10,
        )
        session.add_all([active_session, already_revoked_session, credential])
        session.flush()
        open_run = SqlExternalResearchRun(
            credential_id=credential.id,
            project_id=UUID(project_id),
            sponsor_user_id=user.id,
            client_request_id=uuid4(),
            input_revision_ids=[],
        )
        completed_run = SqlExternalResearchRun(
            credential_id=credential.id,
            project_id=UUID(project_id),
            sponsor_user_id=user.id,
            client_request_id=uuid4(),
            input_revision_ids=[],
            status="COMPLETED",
            closed_at=utc_now(),
        )
        session.add_all([open_run, completed_run])
        session.commit()

        try:
            invalidate_restored_protected_access(session, recovery_reference="short")
            raise AssertionError("short recovery references must fail")
        except RestoreInvalidationInvalid:
            session.rollback()

        result = invalidate_restored_protected_access(
            session,
            recovery_reference="restore-case-123",
        )
        assert (result.revoked_sessions, result.revoked_credentials, result.revoked_runs) == (
            1,
            1,
            1,
        )
        session.expire_all()
        assert session.get(SqlAuthSession, active_session.id).revoked_at is not None
        assert session.get(SqlAuthSession, already_revoked_session.id).revoked_at is not None
        assert session.get(SqlExternalAgentCredential, credential.id).revoked_at is not None
        assert session.get(SqlExternalResearchRun, open_run.id).status == "REVOKED"
        assert session.get(SqlExternalResearchRun, completed_run.id).status == "COMPLETED"
        audit = session.query(SqlOperatorRestoreInvalidation).one()
        assert audit.recovery_reference_digest == hashlib.sha256(b"restore-case-123").hexdigest()

        repeated = invalidate_restored_protected_access(
            session,
            recovery_reference="restore-case-repeat",
        )
        assert (repeated.revoked_sessions, repeated.revoked_credentials, repeated.revoked_runs) == (
            0,
            0,
            0,
        )


def test_restore_invalidation_cli_requires_explicit_confirmation() -> None:
    with pytest.raises(SystemExit) as denied:
        restore_invalidation_main(["--recovery-reference", "restore-case-123"])
    assert denied.value.code == 2


def test_recent_public_submissions_cap_and_visibility(client: TestClient) -> None:
    enable_research(client)
    public = create_workspace(client)
    other = create_workspace(client, "Second public workspace")
    create_human_claim(client, public["id"], "First public claim")
    create_human_claim(client, other["id"], "Second public claim")
    private = client.post(
        "/api/v1/workspaces", headers=headers(), json={"name": "Private", "visibility": "PRIVATE"}
    ).json()
    create_human_claim(client, private["id"], "Private claim")
    with cast(Any, client.app).state.session_factory() as session:
        events = list(session.scalars(select(SqlResearchActivityEvent)))
        # Backdated public events prove the feed is not limited to the last month.
        public_ids = {row["object_id"] for row in client.get("/api/v1/activity").json()["items"]}
        base = next(event for event in events if str(event.object_id) in public_ids)
        start = utc_now() - timedelta(days=60)
        for index in range(505):
            session.add(
                SqlResearchActivityEvent(
                    id=uuid4(),
                    source_kind="ObjectRevision",
                    source_id=uuid4(),
                    ownership_scope_id=base.ownership_scope_id,
                    object_id=base.object_id,
                    revision_id=base.revision_id,
                    action="object.created",
                    occurred_at=start - timedelta(seconds=index),
                    reconstructed=True,
                )
            )
        session.commit()
    cursor = None
    seen: list[str] = []
    numbers: dict[str, int] = {}
    for _ in range(10):
        response = client.get(
            "/api/v1/activity",
            params={"recent": True, "limit": 50, **({"cursor": cursor} if cursor else {})},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert len(data["items"]) == 50
        assert all(row["workspace_id"] in {public["id"], other["id"]} for row in data["items"])
        assert all(
            row["workspace_name"] and row["object_version_number"] == 1 for row in data["items"]
        )
        seen.extend(row["id"] for row in data["items"])
        numbers.update({row["id"]: row["submission_number"] for row in data["items"]})
        cursor = data["next_cursor"]
    assert cursor is None
    assert len(set(seen)) == 500
    assert len(set(numbers.values())) == 500
    filtered = client.get("/api/v1/activity?recent=true&actor=human&limit=50").json()["items"]
    assert all(numbers[row["id"]] == row["submission_number"] for row in filtered)
    assert (
        client.get("/api/v1/activity?recent=true&scope=member", headers=headers()).status_code
        == 422
    )
