"""External credentials use the same project file authority and conflict boundary."""

from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_default_files import files as files
from test_sessions_api import add_member, headers

from polycolab.db.models import SqlExternalAgentCredential
from polycolab.entities.time import utc_now
from polycolab.projects.default_files import DefaultFiles
from polycolab.projects.file_access import FileAccess


def test_files_require_authentication_in_runtime_and_contract(
    files: tuple[TestClient, str, Path],
) -> None:
    client, root, _ = files
    assert client.get(root).status_code == 401
    operations = client.get("/api/openapi.json").json()["paths"][
        "/api/v1/projects/{project_id}/files"
    ]
    for method in ("get", "post"):
        assert {} not in operations[method]["security"]
        assert {"ExternalAgentBearer": []} in operations[method]["security"]


def key_for(client: TestClient, user: str = "owner") -> dict[str, Any]:
    identity = client.post("/api/v1/account/agents", headers=headers(user), json={"name": "Files"})
    assert identity.status_code == 201, identity.text
    response = client.post(
        "/api/v1/account/agent-keys",
        headers=headers(user),
        json={
            "name": "Files",
            "agent_id": identity.json()["id"],
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_external_file_crud_and_conflicts(files: tuple[TestClient, str, Path]) -> None:
    client, root, directory = files
    key = key_for(client)
    auth = headers(key["secret"])
    response = client.post(
        root, headers=auth, json={"action": "write", "path": "a", "content": "agent"}
    )
    assert response.status_code == 200, response.text
    digest = response.json()["digest"]
    assert client.get(root, headers=auth).json()["files"][0]["path"] == "a"
    assert (
        client.post(root, headers=auth, json={"action": "read", "path": "a"}).json()["content"]
        == "agent"
    )
    assert (
        client.post(
            root,
            headers=headers("owner"),
            json={
                "action": "write",
                "path": "a",
                "content": "human",
                "expected_digest": digest,
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            root,
            headers=auth,
            json={
                "action": "write",
                "path": "a",
                "content": "stale",
                "expected_digest": digest,
            },
        ).status_code
        == 409
    )
    current = client.post(root, headers=auth, json={"action": "read", "path": "a"}).json()
    moved = client.post(
        root,
        headers=auth,
        json={
            "action": "rename",
            "path": "a",
            "destination": "b",
            "expected_digest": current["digest"],
        },
    )
    assert moved.status_code == 200
    assert (
        client.post(
            root,
            headers=auth,
            json={
                "action": "delete",
                "path": "b",
                "expected_digest": moved.json()["digest"],
            },
        ).status_code
        == 200
    )
    assert not (directory / "b").exists()


def test_external_member_authority(files: tuple[TestClient, str, Path]) -> None:
    client, root, _ = files
    project = root.split("/")[-2]
    outsider = key_for(client, "outsider")
    assert client.get(root, headers=headers(outsider["secret"])).status_code == 404
    add_member(client, project, "reader", "READ_ONLY")
    reader = key_for(client, "reader")
    assert client.get(root, headers=headers(reader["secret"])).status_code == 200
    assert (
        client.post(
            root,
            headers=headers(reader["secret"]),
            json={
                "action": "write",
                "path": "no",
                "content": "no",
            },
        ).status_code
        == 403
    )
    key = key_for(client)
    assert (
        client.patch(
            f"/api/v1/projects/{project}",
            headers=headers("owner"),
            json={"archived": True},
        ).status_code
        == 200
    )
    assert client.get(root, headers=headers(key["secret"])).status_code == 200
    assert (
        client.post(
            root,
            headers=headers(key["secret"]),
            json={
                "action": "write",
                "path": "no",
                "content": "no",
            },
        ).status_code
        == 403
    )


@pytest.mark.parametrize("condition", ["expired", "revoked", "requests", "mutations", "project"])
def test_invalid_or_exhausted_key_cannot_write(
    files: tuple[TestClient, str, Path], condition: str
) -> None:
    client, root, directory = files
    key = key_for(client)
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        row = db.get(SqlExternalAgentCredential, UUID(key["id"]))
        if condition == "expired":
            row.expires_at = utc_now() - timedelta(seconds=1)
        elif condition == "revoked":
            row.revoked_at = utc_now()
        elif condition == "requests":
            row.request_count = row.max_requests
        elif condition == "mutations":
            row.mutation_count = row.max_mutations
        else:
            other = client.post(
                "/api/v1/projects", headers=headers("owner"), json={"name": "Other"}
            ).json()
            row.scope_kind, row.project_id = "PROJECT", UUID(other["id"])
        db.commit()
    response = client.post(
        root,
        headers=headers(key["secret"]),
        json={
            "action": "write",
            "path": "no",
            "content": "no",
        },
    )
    expected = {
        "expired": 401,
        "revoked": 401,
        "requests": 429,
        "mutations": 429,
        "project": 404,
    }
    assert response.status_code == expected[condition], response.text
    assert not (directory / "no").exists()


def test_project_key_is_bound_to_its_project(
    files: tuple[TestClient, str, Path],
) -> None:
    client, root, _ = files
    key = key_for(client)
    with cast(Any, client.app).state.session_factory() as db:
        row = db.get(SqlExternalAgentCredential, UUID(key["id"]))
        row.scope_kind, row.project_id = "PROJECT", UUID(root.split("/")[-2])
        db.commit()
    assert client.get(root, headers=headers(key["secret"])).status_code == 200


def test_revocation_after_admission_prevents_write(
    files: tuple[TestClient, str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, root, directory = files
    key = key_for(client)
    original = FileAccess.bind

    def revoked(access: FileAccess, db: Session, instance: DefaultFiles, *, write: bool) -> None:
        with cast(Any, client.app).state.session_factory() as revoke_db:
            revoke_db.get(SqlExternalAgentCredential, UUID(key["id"])).revoked_at = utc_now()
            revoke_db.commit()
        original(access, db, instance, write=write)

    monkeypatch.setattr(FileAccess, "bind", revoked)
    response = client.post(
        root,
        headers=headers(key["secret"]),
        json={"action": "write", "path": "no", "content": "no"},
    )
    assert response.status_code == 401, response.text
    assert not (directory / "no").exists()


@pytest.mark.parametrize("client", ["file"], indirect=True)
def test_concurrent_agent_writes_cannot_exceed_budget(
    files: tuple[TestClient, str, Path],
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    client, root, directory = files
    key = key_for(client)
    with cast(Any, client.app).state.session_factory() as db:
        db.get(SqlExternalAgentCredential, UUID(key["id"])).max_mutations = 1
        db.commit()

    def write(name: str) -> int:
        response = client.post(
            root,
            headers=headers(key["secret"]),
            json={"action": "write", "path": name, "content": name},
        )
        return int(response.status_code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, ["one", "two"])) == [200, 429]
    assert len(list(directory.iterdir())) == 1
