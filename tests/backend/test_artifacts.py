from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from research_requests import post_research
from sqlalchemy import delete, select
from test_research_domain import add_member, create_object, create_workspace, headers

from polycolab.artifacts import cleanup
from polycolab.artifacts.storage import GarageStorage
from polycolab.db.models import SqlArtifact, SqlArtifactResearchLink, SqlMembership, SqlProject
from polycolab.db.transaction import SqlAlchemyTransaction, make_transaction_factory
from polycolab.entities.enums import ArtifactState
from polycolab.entities.time import utc_now


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


@pytest.fixture
def artifact_client(client: TestClient) -> TestClient:
    app = cast(Any, client.app)
    app.state.artifact_storage = GarageStorage(MemoryS3(), "private-test")
    return client


def upload(client: TestClient, project: str, data: bytes = b"abc", **kwargs: Any) -> Any:
    return client.post(
        "/api/v1/artifacts",
        content=data,
        headers=headers("owner"),
        params={
            "workspace_id": project,
            "sha256": hashlib.sha256(data).hexdigest(),
            "byte_length": len(data),
            **kwargs,
        },
    )


def attach(client: TestClient, project: str, artifact: str, revision: str) -> Any:
    return post_research(
        client,
        "/api/v1/attachments",
        headers=headers("owner"),
        json={"artifact_id": artifact, "object_version_id": revision, "role": "EVIDENCE"},
    )


def test_upload_commit_private_download_and_retry(artifact_client: TestClient) -> None:
    client = artifact_client
    project = create_workspace(client)
    target = create_object(client, project)
    response = upload(client, project, b"<script>bad()</script>", media_type="text/html")
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["state"] == "STAGING"
    assert "storage_key" not in result
    url = f"/api/v1/artifacts/{result['id']}/content"
    assert client.get(url, headers=headers("owner")).status_code == 404
    first = attach(client, project, result["id"], target["current_object_version_id"])
    assert first.status_code == 200, first.text
    assert (
        attach(client, project, result["id"], target["current_object_version_id"]).json()
        == first.json()
    )
    response = client.get(url, headers=headers("owner"))
    assert response.status_code == 200
    assert response.content == b"<script>bad()</script>"
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert client.get(url).status_code == 404


def test_artifact_contract_uses_explicit_object_versions(artifact_client: TestClient) -> None:
    from polycolab.db.models import SqlMutationReceipt
    from polycolab.platform.outbox import canonical_digest

    client = artifact_client
    project = create_workspace(client)
    target = create_object(client, project)
    version_id = target["current_object_version_id"]
    artifact = upload(client, project).json()
    body = {"artifact_id": artifact["id"], "object_version_id": version_id, "role": "EVIDENCE"}
    retry_headers = headers("owner")
    attached = client.post("/api/v1/attachments", headers=retry_headers, json=body)
    assert attached.status_code == 200, attached.text
    repeated = client.post("/api/v1/attachments", headers=retry_headers, json=body)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["outputs"] == attached.json()["outputs"]
    assert repeated.json()["contribution_id"] == attached.json()["contribution_id"]
    assert repeated.json()["replayed"] is True
    with cast(Any, client.app).state.session_factory() as session:
        saved = session.get(SqlArtifact, UUID(artifact["id"]))
        assert saved is not None
        receipt = session.scalar(
            select(SqlMutationReceipt).where(
                SqlMutationReceipt.operation == "direct.artifact.attach",
                SqlMutationReceipt.idempotency_key_digest
                == canonical_digest(retry_headers["Idempotency-Key"]),
            )
        )
        assert receipt is not None
        assert receipt.request_digest == canonical_digest(
            {
                "version": 1,
                "payload": {
                    "destination_scope_id": str(saved.ownership_scope_id),
                    "payload": {
                        "artifact_id": artifact["id"],
                        "revision_id": version_id,
                        "attempt_revision_id": None,
                        "role": "EVIDENCE",
                    },
                },
            }
        )
    old_body = {key: value for key, value in body.items() if key != "object_version_id"}
    old_body["revision_id"] = version_id
    assert (
        client.post("/api/v1/attachments", headers=headers("owner"), json=old_body).status_code
        == 422
    )
    exact = client.get(f"/api/v1/versions/{version_id}/attachments", headers=headers("owner"))
    assert exact.status_code == 200, exact.text
    assert exact.json()["items"][0]["object_version_id"] == version_id
    assert client.get(f"/api/v1/versions/{version_id}/attachments").status_code == 404
    assert (
        client.get(
            f"/api/v1/revisions/{version_id}/attachments", headers=headers("owner")
        ).status_code
        == 404
    )
    paths = cast(Any, client.app).openapi()["paths"]
    assert "/api/v1/revisions/{revision_id}/attachments" not in paths
    assert "/api/v1/versions/{object_version_id}/attachments" in paths


def test_attachment_pages_preserve_links_filter_before_paging_and_never_read_storage(
    artifact_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = artifact_client
    project, other = create_workspace(client), create_workspace(client)
    first, second = create_object(client, project), create_object(client, project)
    foreign = create_object(client, other)
    row = upload(
        client, project, source_object_version_id=first["current_object_version_id"]
    ).json()
    foreign_row = upload(client, other).json()
    links = [
        attach(client, project, row["id"], target["current_object_version_id"]).json()["id"]
        for target in (first, second)
    ]
    assert (
        attach(client, other, foreign_row["id"], foreign["current_object_version_id"]).status_code
        == 200
    )
    upload(client, project)  # Unattached staging identity is not enumerable.

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("enumeration must not create an object-store client")

    monkeypatch.setattr("polycolab.artifacts.routes.private.artifact_storage", fail)
    url = f"/api/v1/workspaces/{project}/artifacts"
    page = client.get(url, headers=headers("owner"), params={"limit": 1})
    assert page.status_code == 200
    assert page.headers["cache-control"] == "private, no-store"
    assert "x-total-count" not in page.headers
    body = page.json()
    item = body["items"][0]
    assert set(item) == {
        "attachment_id",
        "artifact",
        "source_object_version_id",
        "object_version_id",
        "attempt_object_version_id",
        "role",
        "created_at",
    }
    assert set(item["artifact"]) == {
        "id",
        "sha256",
        "byte_length",
        "media_type",
        "state",
        "expires_at",
    }
    assert item["artifact"]["state"] == "COMMITTED"
    assert item["source_object_version_id"] == first["current_object_version_id"]
    assert item["attempt_object_version_id"] is None and item["role"] == "EVIDENCE"
    tail = client.get(
        url, headers=headers("owner"), params={"limit": 1, "cursor": body["next_cursor"]}
    ).json()
    assert [item["attachment_id"], tail["items"][0]["attachment_id"]] == sorted(links)
    assert tail["next_cursor"] is None
    assert tail["items"][0]["artifact"]["id"] == row["id"]
    filtered = client.get(
        url,
        headers=headers("owner"),
        params={"limit": 1, "object_version_id": second["current_object_version_id"]},
    ).json()
    assert filtered["next_cursor"] is None
    assert [item["object_version_id"] for item in filtered["items"]] == [
        second["current_object_version_id"]
    ]
    assert (
        client.get(
            url,
            headers=headers("owner"),
            params={"object_version_id": foreign["current_object_version_id"]},
        ).status_code
        == 404
    )
    assert (
        client.get(
            url, headers=headers("owner"), params={"object_version_id": str(uuid4())}
        ).status_code
        == 404
    )


def test_attachment_page_retains_exact_attempt_binding(artifact_client: TestClient) -> None:
    client = artifact_client
    project = create_workspace(client)
    target = create_object(client, project)["current_object_version_id"]
    attempt = post_research(
        client,
        "/api/v1/objects",
        headers=headers("owner"),
        json={
            "destination": {"kind": "workspace", "workspace_id": project},
            "snapshot": {
                "kind": "ATTEMPT",
                "content": {
                    "title": "Explore",
                    "content_md": "Partial evidence",
                    "assumptions_md": "None",
                    "reported_outcome": None,
                    "explanation_md": None,
                    "outcome": "POTENTIAL",
                    "findings_md": "Try a bound",
                },
                "structural_relationships": [
                    {"relationship_type": "TARGET", "target_object_version_id": target}
                ],
            },
        },
    )
    assert attempt.status_code == 201, attempt.text
    attempt_revision = attempt.json()["current_object_version_id"]
    artifact = upload(client, project).json()["id"]
    link = post_research(
        client,
        "/api/v1/attachments",
        headers=headers("owner"),
        json={
            "artifact_id": artifact,
            "object_version_id": target,
            "attempt_object_version_id": attempt_revision,
            "role": "OUTPUT",
        },
    )
    assert link.status_code == 200, link.text
    item = client.get(f"/api/v1/workspaces/{project}/artifacts", headers=headers("owner")).json()[
        "items"
    ][0]
    assert item["attachment_id"] == link.json()["id"]
    assert item["object_version_id"] == target
    assert item["attempt_object_version_id"] == attempt_revision
    assert item["source_object_version_id"] is None and item["role"] == "OUTPUT"


def test_attachment_list_authorization_and_archived_reads(
    artifact_client: TestClient,
) -> None:
    client = artifact_client
    project = create_workspace(client)
    add_member(client, project, "reader", "READ_ONLY")
    revision = create_object(client, project)["current_object_version_id"]
    row = upload(client, project).json()
    assert attach(client, project, row["id"], revision).status_code == 200
    url = f"/api/v1/workspaces/{project}/artifacts"
    assert client.get(url).status_code == 404
    assert client.get(url, headers=headers("outsider")).status_code == 404
    app = cast(Any, client.app)
    with app.state.session_factory() as session:
        stored = session.get(SqlProject, UUID(project))
        stored.archived_at = utc_now()
        session.commit()
    assert len(client.get(url, headers=headers("reader")).json()["items"]) == 1
    reader = client.get("/api/v1/users/me", headers=headers("reader")).json()["id"]
    with app.state.session_factory() as session:
        session.execute(
            delete(SqlMembership).where(
                SqlMembership.project_id == UUID(project), SqlMembership.user_id == UUID(reader)
            )
        )
        session.commit()
    assert client.get(url, headers=headers("reader")).status_code == 404
    assert client.get(url, headers=headers("owner")).status_code == 200


@pytest.mark.parametrize(
    "state", [ArtifactState.STAGING, ArtifactState.DELETING, ArtifactState.DELETED]
)
def test_attachment_list_excludes_noncommitted_states(
    artifact_client: TestClient, state: ArtifactState
) -> None:
    client = artifact_client
    project = create_workspace(client)
    row = upload(client, project).json()
    revision = create_object(client, project)["current_object_version_id"]
    assert attach(client, project, row["id"], revision).status_code == 200
    # SQLite deliberately seeds otherwise invalid lifecycle states to exercise
    # read-side exclusion; PostgreSQL enforces the real transition invariants.
    with cast(Any, client.app).state.session_factory() as session:
        stored = session.get(SqlArtifact, UUID(row["id"]))
        stored.state = state
        stored.committed_at = None
        stored.deleted_at = utc_now() if state is ArtifactState.DELETED else None
        session.commit()
    response = client.get(f"/api/v1/workspaces/{project}/artifacts", headers=headers("owner"))
    assert response.json() == {"items": [], "next_cursor": None}


@pytest.mark.parametrize(
    "params,status",
    [({"cursor": "bad"}, 422), ({"cursor": ""}, 422), ({"limit": 0}, 422), ({"limit": 101}, 422)],
)
def test_attachment_list_rejects_invalid_paging(
    artifact_client: TestClient, params: dict[str, Any], status: int
) -> None:
    project = create_workspace(artifact_client)
    response = artifact_client.get(
        f"/api/v1/workspaces/{project}/artifacts", headers=headers("owner"), params=params
    )
    assert response.status_code == status


def test_matching_hash_and_known_id_do_not_grant_access(artifact_client: TestClient) -> None:
    client = artifact_client
    first, second = create_workspace(client), create_workspace(client)
    one = upload(client, first).json()
    two = upload(client, second).json()
    assert one["sha256"] == two["sha256"] and one["id"] != two["id"]
    url = f"/api/v1/artifacts/{one['id']}"
    # The canonical artifact URL resolves the owner’s actual workspace membership.
    assert client.get(url, headers=headers("owner")).status_code == 200
    assert client.get(url, headers=headers("outsider")).status_code == 404
    target = create_object(client, first)
    assert attach(client, second, two["id"], target["current_object_version_id"]).status_code == 404


def test_revocation_denies_committed_bytes(artifact_client: TestClient) -> None:
    client = artifact_client
    project = create_workspace(client)
    add_member(client, project, "reader", "READ_ONLY")
    target = create_object(client, project)
    row = upload(client, project).json()
    assert (
        attach(client, project, row["id"], target["current_object_version_id"]).status_code == 200
    )
    url = f"/api/v1/artifacts/{row['id']}/content"
    assert client.get(url, headers=headers("reader")).status_code == 200
    reader = client.get("/api/v1/users/me", headers=headers("reader")).json()["id"]
    with cast(Any, client.app).state.session_factory() as session:
        session.execute(
            delete(SqlMembership).where(
                SqlMembership.project_id == UUID(project), SqlMembership.user_id == UUID(reader)
            )
        )
        session.commit()
    assert client.get(url, headers=headers("reader")).status_code == 404


def test_revocation_during_download_prevents_returning_bytes(
    artifact_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = artifact_client
    project = create_workspace(client)
    add_member(client, project, "reader", "READ_ONLY")
    target = create_object(client, project)
    row = upload(client, project).json()
    assert (
        attach(client, project, row["id"], target["current_object_version_id"]).status_code == 200
    )
    reader = UUID(client.get("/api/v1/users/me", headers=headers("reader")).json()["id"])
    app = cast(Any, client.app)
    s3 = app.state.artifact_storage.client
    original = s3.get_object

    def revoke(**kwargs: Any) -> dict[str, Any]:
        with app.state.session_factory() as db:
            db.execute(
                delete(SqlMembership).where(
                    SqlMembership.project_id == UUID(project), SqlMembership.user_id == reader
                )
            )
            db.commit()
        return cast(dict[str, Any], original(**kwargs))

    monkeypatch.setattr(s3, "get_object", revoke)
    response = client.get(f"/api/v1/artifacts/{row['id']}/content", headers=headers("reader"))
    assert response.status_code == 404
    assert response.content != b"abc"


def test_cleanup_storage_failure_and_late_upload_are_recoverable(
    artifact_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import timedelta

    from polycolab.artifacts.cleanup import sweep_page
    from polycolab.artifacts.storage import ArtifactStorageError
    from polycolab.entities.time import utc_now

    client = artifact_client
    project = create_workspace(client)
    staged = upload(client, project).json()
    app = cast(Any, client.app)
    factory = app.state.session_factory
    storage = app.state.artifact_storage
    with factory() as db:
        row = db.get(SqlArtifact, UUID(staged["id"]))
        assert row is not None
        key = row.storage_key
        row.expires_at = utc_now() - timedelta(hours=2)
        db.commit()
    original = storage.client.delete_object

    def unavailable(**kwargs: Any) -> None:
        raise ArtifactStorageError("artifact_storage_unavailable")

    monkeypatch.setattr(storage.client, "delete_object", unavailable)
    result = sweep_page(make_transaction_factory(factory), storage, grace_seconds=0)
    assert result.failure_count == 1 and result.deleted_count == 0
    with factory() as db:
        assert db.get(SqlArtifact, UUID(staged["id"])).state == ArtifactState.DELETING
    monkeypatch.setattr(storage.client, "delete_object", original)
    assert (
        sweep_page(make_transaction_factory(factory), storage, grace_seconds=0).deleted_count == 1
    )
    assert key not in storage.client.objects
    storage.client.objects[key] = b"late completed upload"
    assert (
        sweep_page(make_transaction_factory(factory), storage, grace_seconds=0).deleted_count == 1
    )
    assert key not in storage.client.objects


@pytest.mark.parametrize(
    "params,status",
    [
        ({"sha256": "0" * 64}, 422),
        ({"byte_length": 2}, 413),
        ({"byte_length": 4}, 422),
        ({"media_type": "text/html\r\nx: y"}, 422),
    ],
)
def test_invalid_bytes_never_commit(
    artifact_client: TestClient, params: dict[str, Any], status: int
) -> None:
    client = artifact_client
    project = create_workspace(client)
    assert upload(client, project, **params).status_code == status
    with cast(Any, client.app).state.session_factory() as session:
        assert not list(
            session.scalars(select(SqlArtifact).where(SqlArtifact.state == ArtifactState.COMMITTED))
        )
        assert not list(session.scalars(select(SqlArtifactResearchLink)))


def test_missing_storage_is_unavailable_not_a_disabled_feature(client: TestClient) -> None:
    project = create_workspace(client)
    response = upload(client, project)
    assert response.status_code == 503
    assert "artifact_storage_unavailable" in response.text


def test_artifacts_available_but_readonly_writes_denied(artifact_client: TestClient) -> None:
    client = artifact_client
    project = create_workspace(client)
    add_member(client, project, "reader", "READ_ONLY")
    response = client.post(
        "/api/v1/artifacts",
        headers=headers("reader"),
        content=b"",
        params={
            "workspace_id": project,
            "sha256": hashlib.sha256(b"").hexdigest(),
            "byte_length": 0,
        },
    )
    assert response.status_code == 403
    assert upload(client, project).status_code == 201


def test_unverified_artifact_cannot_attach(artifact_client: TestClient) -> None:
    client = artifact_client
    project = create_workspace(client)
    target = create_object(client, project)
    assert upload(client, project, sha256="0" * 64).status_code == 422
    with cast(Any, client.app).state.session_factory() as session:
        row = session.scalar(select(SqlArtifact))
        assert row is not None and row.verified_at is None
        artifact_id = str(row.id)
    assert (
        attach(client, project, artifact_id, target["current_object_version_id"]).status_code == 409
    )


def test_gc_fences_commit_and_retains_tombstones(artifact_client: TestClient) -> None:
    from datetime import timedelta

    from polycolab.entities.time import utc_now

    client = artifact_client
    project = create_workspace(client)
    target = create_object(client, project)
    staged = upload(client, project).json()
    committed = upload(client, project).json()
    assert (
        attach(client, project, committed["id"], target["current_object_version_id"]).status_code
        == 200
    )
    factory = cast(Any, client.app).state.session_factory
    with factory() as session:
        # SQLite-only expiry setup; PostgreSQL tests seed expired rows at creation.
        for row in session.scalars(select(SqlArtifact)):
            row.expires_at = utc_now() - timedelta(hours=2)
        session.commit()
        claimed = cleanup.claim_expired(SqlAlchemyTransaction(session), grace_seconds=0)
        assert [str(row.id) for row in claimed] == [staged["id"]]
    assert (
        attach(client, project, staged["id"], target["current_object_version_id"]).status_code
        == 404
    )
    with factory() as session:
        cleanup.deleted(SqlAlchemyTransaction(session), artifact_id=UUID(staged["id"]))
        # Re-sweep covers late ambiguous PUTs after the initial deletion.
        assert [
            str(row.id)
            for row in cleanup.claim_expired(SqlAlchemyTransaction(session), grace_seconds=0)
        ] == [staged["id"]]
