"""Shared session execution keeps each sender's authority and private inputs."""

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from test_sessions_api import (
    add_member,
    create_connection,
    create_project,
    create_session,
    headers,
)

from polycolab.conversations.service import set_sharing
from polycolab.db.models import SqlAgentRun, SqlMembership, SqlProviderConnection
from polycolab.db.stores.conversations import SqlConversationStore
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.conversation import ConversationSharing
from polycolab.entities.enums import ProjectRole

WORKER = {"Authorization": "Bearer polycolab-local-runtime-worker-token"}


def shared_session(client: TestClient) -> tuple[Any, UUID, UUID, UUID, dict[str, str]]:
    app = cast(Any, client.app)
    project_id = UUID(str(create_project(client)["id"]))
    add_member(client, str(project_id), "contributor", "CONTRIBUTOR")
    add_member(client, str(project_id), "reader", "READ_ONLY")
    session_id = UUID(str(create_session(client, str(project_id))["id"]))
    owner_id = UUID(client.get("/api/v1/account", headers=headers("owner")).json()["id"])
    sender_id = UUID(client.get("/api/v1/account", headers=headers("contributor")).json()["id"])
    with app.state.session_factory() as db:
        set_sharing(
            SqlAlchemyTransaction(db),
            session_id,
            owner_id,
            ConversationSharing.PROJECT_CONTRIBUTABLE,
        )
    profile = create_connection(client, "contributor")
    message = {
        "type": "message",
        "client_request_id": str(uuid4()),
        "content_md": "Contribute with my own model profile.",
        "provider_connection_id": str(profile["id"]),
    }
    return app, project_id, session_id, sender_id, message


def test_shared_submission_profiles_retries_and_owner_interruption(
    client: TestClient,
) -> None:
    app, _, session_id, sender_id, message = shared_session(client)
    path = f"/api/v1/sessions/{session_id}/events"
    owner_profile = create_connection(client, "owner")
    stolen_profile = client.post(
        path,
        headers=headers("contributor"),
        json={**message, "provider_connection_id": owner_profile["id"]},
    )
    assert stolen_profile.status_code == 409
    assert client.post(path, headers=headers("reader"), json=message).status_code == 403
    accepted = client.post(path, headers=headers("contributor"), json=message)
    assert accepted.status_code == 202, accepted.text
    acknowledgement = accepted.json()
    run_id = UUID(acknowledgement["run"]["id"])
    assert acknowledgement["item"]["author"]["user_id"] == str(sender_id)
    retry = client.post(path, headers=headers("contributor"), json=message)
    assert retry.json() == acknowledgement
    assert (
        client.post(
            path,
            headers=headers("contributor"),
            json={**message, "content_md": "Changed input"},
        ).status_code
        == 409
    )
    assert client.post(path, headers=headers("owner"), json=message).status_code == 409
    with app.state.session_factory() as db:
        run = db.get(SqlAgentRun, run_id)
        profile = db.get(SqlProviderConnection, UUID(message["provider_connection_id"]))
        assert run is not None and profile is not None
        assert run.requested_by_user_id == sender_id == profile.user_id
        assert run.provider_connection_id == profile.id
        assert run.gateway_credential_version == profile.credential_version
    assert (
        client.patch(
            f"/api/v1/sessions/{session_id}",
            headers=headers("contributor"),
            json={"archived": True},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/sessions/{session_id}/events",
            headers=headers("reader"),
            json={"type": "interrupt", "run_id": str(run_id)},
        ).status_code
        == 403
    )
    cancelled = client.post(
        f"/api/v1/sessions/{session_id}/events",
        headers=headers("owner"),
        json={"type": "interrupt", "run_id": str(run_id)},
    )
    assert cancelled.status_code == 202 and cancelled.json()["run"]["status"] == "CANCELLED"
    resume = client.post(
        f"/api/v1/runs/{run_id}/resume",
        headers=headers("contributor"),
        json={
            "client_request_id": str(uuid4()),
            "provider_connection_id": message["provider_connection_id"],
        },
    )
    assert resume.status_code == 202, resume.text
    assert resume.json()["parent_run_id"] == str(run_id)
    # Interrupting the old identity does not cancel its independently queued successor.
    client.post(
        f"/api/v1/sessions/{session_id}/events",
        headers=headers("owner"),
        json={"type": "interrupt", "run_id": str(run_id)},
    )
    assert (
        client.get(f"/api/v1/runs/{resume.json()['id']}", headers=headers("contributor")).json()[
            "status"
        ]
        == "QUEUED"
    )
    with app.state.session_factory() as db:
        store = SqlConversationStore(db)
        history = store.executions(session_id)
        successor_page = store.executions(session_id, after=history[0].sequence)
        latest = store.latest_executions([session_id])[session_id]
        execution = store.execution(run_id)
    assert [value.sequence for value in history] == [1, 2]
    assert successor_page == history[1:]
    assert latest.id == UUID(resume.json()["id"])
    assert execution is not None and execution.requested_by_user_id == sender_id
    assert execution.context is not None and execution.context.artifact_ids == ()
    assert execution.summary.requested_model == "research-model"
    assert execution.summary.observed_model is None
    assert execution.usage is not None and execution.usage.observations == ()
    assert history[0].usage is None  # Summaries do not implicitly load accounting.


@pytest.mark.parametrize("revocation", ["private", "readable", "membership", "role"])
def test_worker_rechecks_shared_sender_authority(client: TestClient, revocation: str) -> None:
    app, project_id, session_id, sender_id, message = shared_session(client)
    response = client.post(
        f"/api/v1/sessions/{session_id}/events",
        headers=headers("contributor"),
        json={"type": "message", **(message)},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["run"]["id"]
    claim = client.post(
        "/internal/v1/runtime/claims",
        headers=WORKER,
        json={"worker_id": "shared-worker"},
    )
    assert claim.status_code == 200, claim.text
    assert claim.json()["run_id"] == run_id
    lease = {
        "worker_id": "shared-worker",
        "lease_generation": claim.json()["lease_generation"],
    }
    capability = {"Authorization": f"Bearer {claim.json()['tool_capability']}"}
    assert (
        client.post(
            "/internal/v1/tools/call",
            headers=capability,
            json={"name": "get_context", "arguments": {}},
        ).status_code
        == 200
    )
    # Context manifests are worker-only in the workspace API, even for the sender.
    for viewer in ("contributor", "owner", "reader"):
        assert (
            client.get(f"/api/v1/runs/{run_id}/context", headers=headers(viewer)).status_code == 404
        )
    for other in ("owner", "reader"):
        assert (
            client.get(f"/api/v1/runs/{run_id}/artifacts", headers=headers(other)).status_code
            == 404
        )
    with app.state.session_factory() as db:
        if revocation in {"private", "readable"}:
            owner_id = UUID(client.get("/api/v1/account", headers=headers("owner")).json()["id"])
            set_sharing(
                SqlAlchemyTransaction(db),
                session_id,
                owner_id,
                ConversationSharing.PRIVATE
                if revocation == "private"
                else ConversationSharing.PROJECT_READABLE,
            )
        elif revocation == "membership":
            db.execute(
                delete(SqlMembership).where(
                    SqlMembership.project_id == project_id,
                    SqlMembership.user_id == sender_id,
                )
            )
            db.commit()
        else:
            membership = db.scalar(
                select(SqlMembership).where(
                    SqlMembership.project_id == project_id,
                    SqlMembership.user_id == sender_id,
                )
            )
            assert membership is not None
            membership.role = ProjectRole.READ_ONLY
            db.commit()
    assert (
        client.post(
            "/internal/v1/tools/call",
            headers=capability,
            json={"name": "get_context", "arguments": {}},
        ).status_code
        == 401
    )
    for endpoint, extra in (
        ("lease", {}),
        ("model-grants", {}),
        (
            "events",
            {
                "kind": "ASSISTANT_DELTA",
                "idempotency_key": "revoked",
                "payload": {"text": "No"},
            },
        ),
        ("finish", {"status": "COMPLETED", "final_message_md": "No"}),
    ):
        result = client.post(
            f"/internal/v1/runtime/runs/{run_id}/{endpoint}",
            headers=WORKER,
            json={**lease, **extra},
        )
        assert result.status_code == 409, result.text
        assert result.json()["error"]["code"] == "authorization_revoked"
    # Revocation stops new work; the worker can still settle observed usage and terminate.
    assert (
        client.post(
            f"/internal/v1/runtime/runs/{run_id}/usage",
            headers=WORKER,
            json={
                **lease,
                "idempotency_key": "settle",
                "input_tokens": 2,
                "output_tokens": 1,
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/internal/v1/runtime/runs/{run_id}/finish",
            headers=WORKER,
            json={**lease, "status": "FAILED", "failure_code": "authorization_revoked"},
        ).status_code
        == 204
    )
