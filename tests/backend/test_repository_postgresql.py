"""The real database contract; uses an isolated disposable PostgreSQL schema."""

from pathlib import Path

import pytest
import test_hosted_repository as hosted
import test_workspace_repository as cases
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from test_sessions_api import create_profile, create_workspace, headers

from polycolab.accounts.authentication import MappingIdentityVerifier
from polycolab.app.application import create_app
from polycolab.platform.config import Settings


@pytest.mark.parametrize("scenario", ["save", "recovery", "hosted"])
def test_repository_postgresql(
    pg_schema: tuple[Engine, Config, str],
    identity_verifier: MappingIdentityVerifier,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(
            database_url=url,
            web_dist_dir="/missing-web-dist",
            feature_agent_execution_enabled=True,
            workspace_repository_directory=tmp_path / "repos",
        ),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            if scenario == "hosted":
                hosted.test_hosted_checkout_save_completion_and_fencing(pg_client, tmp_path, False)
            else:
                created = pg_client.post(
                    "/api/v1/workspaces",
                    headers=cases.OWNER,
                    json={"name": "Files", "visibility": "PUBLIC"},
                )
                assert created.status_code == 201, created.text
                fixture = (pg_client, f"/api/v1/workspaces/{created.json()['id']}/repository")
                if scenario == "save":
                    cases.test_files_history_retry_and_stale_save(fixture)
                else:
                    cases.test_reconcile_saved_ref_after_sql_failure(fixture, monkeypatch)
    finally:
        app.state.engine.dispose()


@pytest.mark.parametrize("scenario", ["task_privacy", "task_runs", "task_claim_race"])
def test_workspace_tasks_postgresql(
    pg_schema: tuple[Engine, Config, str],
    identity_verifier: MappingIdentityVerifier,
    tmp_path: Path,
    scenario: str,
) -> None:
    import test_workspace_tasks as tasks

    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(
            database_url=url,
            web_dist_dir="/missing-web-dist",
            feature_agent_execution_enabled=True,
            workspace_repository_directory=tmp_path / "repos",
        ),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            workspace_id = str(create_workspace(pg_client)["id"])
            if scenario == "task_privacy":
                tasks.test_task_working_copy_retry_archive_and_member_privacy(
                    (pg_client, workspace_id)
                )
            elif scenario == "task_runs":
                tasks.test_task_serializes_runs_across_private_chats_and_pins_shared_branch(
                    (pg_client, workspace_id)
                )
            else:
                from concurrent.futures import ThreadPoolExecutor
                from datetime import timedelta
                from threading import Barrier
                from uuid import uuid4

                from polycolab.agents.sessions import claim_next_run

                task = tasks.create_task(pg_client, workspace_id)
                profile = create_profile(pg_client, "owner")
                for _ in range(2):
                    chat = tasks.task_chat(pg_client, workspace_id, task["id"])
                    response = pg_client.post(
                        f"/api/v1/agent-sessions/{chat['id']}/messages",
                        headers=headers("owner"),
                        json={
                            "client_request_id": str(uuid4()),
                            "content_md": "Task intent",
                            "gateway_profile_id": profile["id"],
                        },
                    )
                    assert response.status_code == 202, response.text
                barrier = Barrier(2)

                def claim(worker_id: str) -> str | None:
                    with app.state.session_factory() as db:
                        barrier.wait(timeout=5)
                        run = claim_next_run(
                            db, worker_id=worker_id, lease_for=timedelta(minutes=1)
                        )
                        return str(run.id) if run else None

                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(claim, ["task-worker-one", "task-worker-two"]))
                assert len([result for result in results if result is not None]) == 1
    finally:
        app.state.engine.dispose()


@pytest.mark.parametrize("scenario", ["files", "agent", "migration", "concurrency"])
def test_native_worktrees_postgresql(
    pg_schema: tuple[Engine, Config, str],
    identity_verifier: MappingIdentityVerifier,
    tmp_path: Path,
    scenario: str,
) -> None:
    from uuid import UUID

    import test_native_worktrees as native

    from polycolab.workspaces.git_storage import GitRepository

    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(
            database_url=url,
            web_dist_dir="/missing-web-dist",
            feature_agent_execution_enabled=True,
            workspace_repository_directory=tmp_path / "repos",
        ),
        identity_verifier,
    )
    try:
        with TestClient(app) as client:
            if scenario == "agent":
                hosted.test_native_agent_sees_saved_overlay_and_leaves_human_review(
                    client, tmp_path
                )
                return
            workspace_id = str(create_workspace(client)["id"])
            fixture = (client, workspace_id, GitRepository(tmp_path / "repos", UUID(workspace_id)))
            if scenario == "files":
                native.test_save_commit_discard_and_remove(fixture)
            elif scenario == "migration":
                native.test_native_migration_retains_old_ids_and_is_resumable(fixture)
            else:
                from concurrent.futures import ThreadPoolExecutor
                from threading import Barrier

                root = f"/api/v1/workspaces/{workspace_id}/worktrees"
                main = client.get(root, headers=headers("owner")).json()[0]
                barrier = Barrier(2)

                def save(key: str) -> int:
                    barrier.wait(timeout=5)
                    response = client.post(
                        root + "/" + main["id"] + "/save",
                        headers={**headers("owner"), "Idempotency-Key": key},
                        json={
                            "expected_revision": main["revision"],
                            "changes": [{"path": key, "content_base64": "eA=="}],
                        },
                    )
                    return int(response.status_code)

                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(save, ["first", "second"]))
                assert sorted(results) == [200, 409]
                state = client.get(root + "/" + main["id"], headers=headers("owner")).json()
                assert state["head_commit"] == main["head_commit"]
                assert len(state["files"]) == 1

    finally:
        app.state.engine.dispose()
