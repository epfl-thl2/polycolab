"""Document builds exercise real Git, private API ownership, and durable leases."""

import base64
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import UUID
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import update
from test_sessions_api import add_member, create_project, headers

from polycolab.artifacts.storage import FilesystemStorage
from polycolab.db.models.document_builds import SqlDocumentBuild
from polycolab.entities.time import utc_now

IMAGE = "sha256:" + "a" * 64
WORKER = {"Authorization": "Bearer test-latex-worker"}
SOURCE = r"\documentclass{article}\begin{document}Hello\end{document}"


@pytest.fixture
def builds(client: TestClient, tmp_path: Path) -> tuple[TestClient, str, dict[str, Any]]:
    app = cast(FastAPI, client.app)
    app.state.settings.project_repository_directory = tmp_path / "repositories"
    app.state.settings.latex_image = IMAGE
    app.state.settings.latex_worker_token = SecretStr("test-latex-worker")
    app.state.artifact_storage = FilesystemStorage(tmp_path / "artifacts")
    project = str(create_project(client)["id"])
    root = f"/api/v1/projects/{project}/worktrees"
    tree = client.get(root, headers=headers("owner")).json()[0]
    root += "/" + tree["id"]
    saved = client.post(
        root + "/save",
        headers={**headers("owner"), "Idempotency-Key": "source"},
        json={
            "expected_revision": tree["revision"],
            "changes": [
                {"path": "main.tex", "content_base64": base64.b64encode(SOURCE.encode()).decode()}
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    assert (
        client.post("/internal/latex/ready", headers=WORKER, json={"image": IMAGE}).status_code
        == 204
    )
    return (
        client,
        root + "/latex-builds",
        {"revision": saved.json()["revision"], "main_file": "main.tex", "engine": "pdflatex"},
    )


def submit(
    client: TestClient, root: str, body: dict[str, Any], key: str = "compile"
) -> dict[str, Any]:
    response = client.post(root, headers={**headers("owner"), "Idempotency-Key": key}, json=body)
    assert response.status_code == 202, response.text
    return cast(dict[str, Any], response.json())


def claim(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/internal/latex/claim", headers=WORKER, json={"worker_id": "test-worker"}
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def test_compile_snapshot_results_and_scope(builds: tuple[TestClient, str, dict[str, Any]]) -> None:
    client, root, body = builds
    build = submit(client, root, body)
    assert submit(client, root, body)["id"] == build["id"]
    assert (
        client.post(
            root,
            headers={**headers("owner"), "Idempotency-Key": "compile"},
            json={**body, "engine": "lualatex"},
        ).status_code
        == 409
    )
    attempt = claim(client)
    assert attempt["id"] == build["id"]
    route = "/internal/latex/" + build["id"]
    generation = {"generation": attempt["generation"]}
    source = client.get(route + "/input", headers=WORKER, params=generation)
    assert source.status_code == 200, source.text
    with ZipFile(BytesIO(source.content)) as archive:
        assert archive.read("main.tex").decode() == SOURCE
        assert archive.namelist() == ["main.tex"]
    # Saving newer text does not change the input of an already admitted build.
    saved = client.post(
        root.removesuffix("/latex-builds") + "/save",
        headers={**headers("owner"), "Idempotency-Key": "new-source"},
        json={
            "expected_revision": body["revision"],
            "changes": [{"path": "main.tex", "content_base64": "bmV3"}],
        },
    )
    assert saved.status_code == 200
    assert client.get(route + "/input", headers=WORKER, params=generation).content == source.content
    pdf = b"%PDF-1.7\nexample"
    for kind, data in (("pdf", pdf), ("log", b"Build finished")):
        response = client.put(
            route + "/outputs/" + kind, headers=WORKER, params=generation, content=data
        )
        assert response.status_code == 204, response.text
    completion = {**generation, "status": "succeeded"}
    assert client.post(route + "/complete", headers=WORKER, json=completion).status_code == 204
    assert client.post(route + "/complete", headers=WORKER, json=completion).status_code == 204
    assert client.post(route + "/release", headers=WORKER, json=generation).status_code == 204
    path = root + "/" + build["id"]
    assert client.get(path, headers=headers("owner")).json()["pdf_available"]
    result = client.get(path + "/outputs/pdf", headers=headers("owner"))
    assert result.content == pdf
    assert result.headers["cache-control"] == "private, no-store"
    project = root.split("/")[4]
    add_member(client, project, "reader", "READ_ONLY")
    assert client.get(path + "/outputs/pdf", headers=headers("reader")).content == pdf
    assert (
        client.post(
            root, headers={**headers("reader"), "Idempotency-Key": "reader"}, json=body
        ).status_code
        == 403
    )
    assert client.get(path + "/outputs/pdf", headers=headers("outsider")).status_code == 404
    assert client.get(path + "/outputs/pdf").status_code == 401
    other_project = str(create_project(client)["id"])
    assert (
        client.get(path.replace(project, other_project), headers=headers("owner")).status_code
        == 404
    )
    other_tree = client.get(
        f"/api/v1/projects/{other_project}/worktrees", headers=headers("owner")
    ).json()[0]["id"]
    assert (
        client.get(
            path.replace(root.split("/")[6], other_tree), headers=headers("owner")
        ).status_code
        == 404
    )


def test_stale_missing_main_and_worker_auth(builds: tuple[TestClient, str, dict[str, Any]]) -> None:
    client, root, body = builds
    auth = {**headers("owner"), "Idempotency-Key": "bad"}
    assert client.post(root, headers=auth, json={**body, "revision": "0" * 40}).status_code == 409
    assert (
        client.post(root, headers=auth, json={**body, "main_file": "missing.tex"}).status_code
        == 422
    )
    assert (
        client.post(
            "/internal/latex/claim", headers=headers("owner"), json={"worker_id": "evil"}
        ).status_code
        == 401
    )
    assert (
        client.post("/internal/latex/ready", headers=WORKER, json={"image": "other"}).status_code
        == 503
    )


def test_cancel_fences_output_and_releases_only_after_stop(
    builds: tuple[TestClient, str, dict[str, Any]],
) -> None:
    client, root, body = builds
    build = submit(client, root, body)
    attempt = claim(client)
    route = "/internal/latex/" + build["id"]
    generation = {"generation": attempt["generation"]}
    assert (
        client.post(root + "/" + build["id"] + "/cancel", headers=headers("owner")).json()["status"]
        == "cancelled"
    )
    assert client.post(route + "/heartbeat", headers=WORKER, json=generation).status_code == 409
    assert (
        client.put(
            route + "/outputs/pdf", headers=WORKER, params=generation, content=b"%PDF-x"
        ).status_code
        == 409
    )
    assert (
        client.post(
            root, headers={**headers("owner"), "Idempotency-Key": "next"}, json=body
        ).status_code
        == 409
    )
    assert client.post(route + "/release", headers=WORKER, json=generation).status_code == 204
    assert submit(client, root, body, "next")["id"] != build["id"]


def test_worker_loss_and_expiry(builds: tuple[TestClient, str, dict[str, Any]]) -> None:
    client, root, body = builds
    build = submit(client, root, body)
    attempt = claim(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.execute(
            update(SqlDocumentBuild)
            .where(SqlDocumentBuild.id == UUID(build["id"]))
            .values(lease_until=utc_now() - timedelta(seconds=1))
        )
        session.commit()
    status = client.get(root + "/" + build["id"], headers=headers("owner")).json()
    assert status["status"] == "failed"
    assert status["error"] == "latex_worker_lost"
    assert (
        client.post(
            "/internal/latex/" + build["id"] + "/complete",
            headers=WORKER,
            json={"generation": attempt["generation"], "status": "succeeded"},
        ).status_code
        == 409
    )


def test_revocation_and_output_limits(builds: tuple[TestClient, str, dict[str, Any]]) -> None:
    from polycolab.db.models import SqlMembership
    from polycolab.entities.enums import ProjectRole

    client, root, body = builds
    build = submit(client, root, body)
    attempt = claim(client)
    route = "/internal/latex/" + build["id"]
    generation = {"generation": attempt["generation"]}
    assert (
        client.put(
            route + "/outputs/pdf", headers=WORKER, params=generation, content=b"not a PDF"
        ).status_code
        == 422
    )
    assert (
        client.put(
            route + "/outputs/log",
            headers=WORKER,
            params=generation,
            content=b"x" * (1024 * 1024 + 1),
        ).status_code
        == 413
    )
    assert (
        client.post(
            route + "/complete", headers=WORKER, json={**generation, "status": "succeeded"}
        ).status_code
        == 409
    )
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.execute(
            update(SqlMembership)
            .where(SqlMembership.project_id == UUID(root.split("/")[4]))
            .values(role=ProjectRole.READ_ONLY)
        )
        session.commit()
    assert client.post(route + "/heartbeat", headers=WORKER, json=generation).status_code == 409
    assert (
        client.get(root + "/" + build["id"], headers=headers("owner")).json()["status"]
        == "cancelled"
    )


def test_expired_bytes_are_collected(builds: tuple[TestClient, str, dict[str, Any]]) -> None:
    from polycolab.db.stores.document_builds import SqlBuildStore
    from polycolab.db.transaction import SqlAlchemyTransaction
    from polycolab.document_builds.service import BuildService
    from polycolab.entities.document_builds import BuildLimits

    client, root, body = builds
    build = submit(client, root, body)
    attempt = claim(client)
    route = "/internal/latex/" + build["id"]
    generation = {"generation": attempt["generation"]}
    assert (
        client.put(
            route + "/outputs/log", headers=WORKER, params=generation, content=b"failed log"
        ).status_code
        == 204
    )
    assert (
        client.post(
            route + "/complete", headers=WORKER, json={**generation, "status": "failed"}
        ).status_code
        == 204
    )
    assert client.post(route + "/release", headers=WORKER, json=generation).status_code == 204
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.execute(
            update(SqlDocumentBuild)
            .where(SqlDocumentBuild.id == UUID(build["id"]))
            .values(
                expires_at=utc_now() - timedelta(days=1), deadline=utc_now() - timedelta(hours=1)
            )
        )
        session.commit()
        service = BuildService(
            SqlAlchemyTransaction(session),
            SqlBuildStore(session),
            app.state.artifact_storage,
            IMAGE,
            BuildLimits(),
        )
        service.cleanup()
        service.cleanup()
        stored = service.store.get(UUID(build["id"]))
        assert stored and not stored.input.key and not stored.outputs
    assert client.get(root + "/" + build["id"], headers=headers("owner")).status_code == 410


def test_list_retains_last_pdf_after_many_failures(
    builds: tuple[TestClient, str, dict[str, Any]],
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from polycolab.db.stores.document_builds import SqlBuildStore

    client, root, body = builds
    build = submit(client, root, body)
    attempt = claim(client)
    route = "/internal/latex/" + build["id"]
    generation = {"generation": attempt["generation"]}
    assert (
        client.put(
            route + "/outputs/pdf", headers=WORKER, params=generation, content=b"%PDF-test"
        ).status_code
        == 204
    )
    assert (
        client.post(
            route + "/complete", headers=WORKER, json={**generation, "status": "succeeded"}
        ).status_code
        == 204
    )
    assert client.post(route + "/release", headers=WORKER, json=generation).status_code == 204
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        store = SqlBuildStore(session)
        original = store.get(UUID(build["id"]))
        assert original
        for index in range(51):
            store.create(
                replace(
                    original,
                    id=uuid4(),
                    request_key=f"failure-{index}",
                    status="failed",
                    outputs={},
                    created_at=original.created_at + timedelta(microseconds=index + 1),
                )
            )
        session.commit()
    listed = client.get(root, headers=headers("owner")).json()["builds"]
    assert listed[0]["status"] == "failed"
    assert [item["id"] for item in listed if item["pdf_available"]] == [build["id"]]
