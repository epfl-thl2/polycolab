"""Real PostgreSQL queue serialization and project/worktree build ownership."""

import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.engine import Engine
from test_document_builds import IMAGE, SOURCE, WORKER, claim, submit
from test_sessions_api import create_project, headers

from polycolab.accounts.authentication import MappingIdentityVerifier
from polycolab.app.application import create_app
from polycolab.artifacts.storage import FilesystemStorage
from polycolab.db.stores.document_builds import SqlBuildStore
from polycolab.entities.time import utc_now
from polycolab.platform.config import Settings


def test_concurrent_claims_respect_capacity_and_completion_scope(
    pg_schema: tuple[Engine, Config, str],
    identity_verifier: MappingIdentityVerifier,
    tmp_path: Path,
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(
            database_url=url,
            web_dist_dir="/missing-latex-test",
            project_repository_directory=tmp_path / "repos",
            latex_image=IMAGE,
            latex_worker_token=SecretStr("test-latex-worker"),
            latex_capacity=1,
        ),
        identity_verifier,
    )
    app.state.artifact_storage = FilesystemStorage(tmp_path / "artifacts")
    try:
        with TestClient(app) as client:
            project = str(create_project(client)["id"])
            root = f"/api/v1/projects/{project}/worktrees"
            main = client.get(root, headers=headers("owner")).json()[0]
            second = client.post(
                root,
                headers=headers("owner"),
                json={
                    "client_request_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
                    "title": "Second",
                    "branch": "second",
                },
            ).json()
            for tree in (main, second):
                path = root + "/" + tree["id"]
                saved = client.post(
                    path + "/save",
                    headers={**headers("owner"), "Idempotency-Key": tree["id"]},
                    json={
                        "expected_revision": tree["revision"],
                        "changes": [
                            {
                                "path": "main.tex",
                                "content_base64": base64.b64encode(SOURCE.encode()).decode(),
                            }
                        ],
                    },
                )
                assert saved.status_code == 200, saved.text
                assert (
                    client.post(
                        "/internal/latex/ready", headers=WORKER, json={"image": IMAGE}
                    ).status_code
                    == 204
                )
                submit(
                    client,
                    path + "/latex-builds",
                    {"revision": saved.json()["revision"], "main_file": "main.tex"},
                )
            barrier = Barrier(2)

            def concurrent_claim() -> dict[str, Any] | None:
                barrier.wait(timeout=10)
                return claim(client)

            with ThreadPoolExecutor(2) as pool:
                attempts = list(pool.map(lambda _: concurrent_claim(), range(2)))
            acquired = [attempt for attempt in attempts if attempt]
            assert len(acquired) == 1
            attempt = acquired[0]
            assert (
                client.post(
                    "/internal/latex/" + attempt["id"] + "/release",
                    headers=WORKER,
                    json={"generation": attempt["generation"]},
                ).status_code
                == 204
            )
            assert claim(client)["id"] != attempt["id"]
            with app.state.session_factory() as session:
                assert SqlBuildStore(session).cleanup_candidates(utc_now())
    finally:
        app.state.engine.dispose()
