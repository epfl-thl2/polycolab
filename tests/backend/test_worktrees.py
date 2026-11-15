from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_sessions_api import add_member, create_connection, create_project, headers

from polycolab.agents.conversations import (
    append_user_message_and_queue_run,
    claim_next_run,
    request_cancel,
    resume_run,
)
from polycolab.db.models import SqlAgentRun
from polycolab.db.stores.repositories import SqlRepositoryStore
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import AgentRunStatus
from polycolab.entities.time import utc_now
from polycolab.projects.git_storage import GitRepository
from polycolab.projects.repository_service import RepositoryService


@pytest.fixture
def tasks(client: TestClient, tmp_path: Path) -> tuple[TestClient, str]:
    app = cast(FastAPI, client.app)
    app.state.settings.project_repository_directory = tmp_path / "repos"
    project_id = str(create_project(client)["id"])
    return client, project_id


def create_task(
    client: TestClient, project_id: str, title: str = "Investigate bound"
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project_id}/worktrees",
        headers=headers("owner"),
        json={
            "title": title,
            "branch": "proof-" + uuid4().hex,
            "client_request_id": str(uuid4()),
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def task_chat(
    client: TestClient, project_id: str, worktree_id: str, token: str = "owner"
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/conversations",
        headers=headers(token),
        json={
            "project_id": project_id,
            "worktree_id": worktree_id,
            "agent_kind": "RESEARCHER",
            "title": "Private secret conversation",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_task_working_copy_retry_archive_and_member_privacy(
    tasks: tuple[TestClient, str],
) -> None:
    client, project_id = tasks
    app = cast(FastAPI, client.app)
    app.state.settings.feature_agent_execution_enabled = False
    task = create_task(client, project_id)
    url = f"/api/v1/projects/{project_id}/worktrees"
    retry = client.post(
        url,
        headers=headers("owner"),
        json={
            "title": task["title"],
            "client_request_id": task["id"],
            "branch": task["branch"],
        },
    )
    assert retry.status_code == 201
    assert retry.json() == task
    assert task in client.get(url, headers=headers("owner")).json()
    repo = client.get(
        f"/api/v1/projects/{project_id}/repository",
        headers=headers("owner"),
        params={"branch": task["branch"]},
    )
    assert repo.status_code == 200, repo.text
    assert repo.json()["writable"]
    app.state.settings.feature_agent_execution_enabled = True
    chat = task_chat(client, project_id, task["id"])
    assert chat["working_context"]["worktree_id"] == task["id"]
    add_member(client, project_id, "reader", "VIEWER")
    assert task["id"] in [row["id"] for row in client.get(url, headers=headers("reader")).json()]
    assert (
        client.get(f"/api/v1/conversations/{chat['id']}", headers=headers("reader")).status_code
        == 404
    )
    assert "Private secret conversation" not in client.get(url, headers=headers("reader")).text
    assert client.get(url, headers=headers("outsider")).status_code == 404
    assert (
        client.patch(
            f"{url}/{task['id']}", headers=headers("reader"), json={"title": "Bad"}
        ).status_code
        == 403
    )
    renamed = client.patch(
        f"{url}/{task['id']}",
        headers=headers("owner"),
        json={"title": "Updated worktree"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "Updated worktree"
    removed = client.post(
        f"{url}/{task['id']}/remove",
        headers={**headers("owner"), "Idempotency-Key": "remove"},
        json={"expected_revision": task["revision"]},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["removed_at"]
    assert [row["branch"] for row in client.get(url, headers=headers("owner")).json()] == ["main"]
    assert (
        len(client.get(url, headers=headers("owner"), params={"include_removed": True}).json()) == 2
    )
    assert client.get(f"{url}/{task['id']}", headers=headers("reader")).status_code == 200
    assert not client.get(
        f"/api/v1/projects/{project_id}/repository",
        headers=headers("owner"),
        params={"branch": task["branch"]},
    ).json()["writable"]
    assert (
        client.post(
            "/api/v1/conversations",
            headers=headers("owner"),
            json={
                "project_id": project_id,
                "worktree_id": task["id"],
                "agent_kind": "RESEARCHER",
            },
        ).status_code
        == 409
    )


def test_task_serializes_runs_across_private_chats_and_pins_shared_branch(
    tasks: tuple[TestClient, str],
) -> None:
    client, project_id = tasks
    app = cast(FastAPI, client.app)
    task = create_task(client, project_id)
    chats = [task_chat(client, project_id, task["id"]) for _ in range(2)]
    profile = create_connection(client, "owner")
    runs = []
    for chat in chats:
        response = client.post(
            f"/api/v1/conversations/{chat['id']}/events",
            headers=headers("owner"),
            json={
                "type": "message",
                **(
                    {
                        "client_request_id": str(uuid4()),
                        "content_md": "Work on task",
                        "provider_connection_id": profile["id"],
                    }
                ),
            },
        )
        assert response.status_code == 202, response.text
        runs.append(response.json()["run"])
    task_url = f"/api/v1/projects/{project_id}/worktrees/{task['id']}"
    assert (
        client.post(
            task_url + "/remove",
            headers={**headers("owner"), "Idempotency-Key": "active"},
            json={"expected_revision": task["revision"]},
        ).status_code
        == 409
    )
    repo_url = f"/api/v1/projects/{project_id}/repository"
    state = client.get(repo_url, headers=headers("owner"), params={"branch": task["branch"]}).json()
    assert not state["writable"]
    denied = client.post(
        repo_url + "/changes",
        headers={**headers("owner"), "Idempotency-Key": "blocked"},
        json={
            "branch": task["branch"],
            "expected_commit": state["commit"],
            "changes": [{"path": "note.md", "content_base64": "bm90ZQ=="}],
        },
    )
    assert denied.status_code == 409
    with app.state.session_factory() as db:
        first = claim_next_run(db, worker_id="worker-one", lease_for=timedelta(minutes=1))
        assert first is not None and str(first.id) == runs[0]["id"]
        assert claim_next_run(db, worker_id="worker-two", lease_for=timedelta(minutes=1)) is None
        service = RepositoryService(
            SqlAlchemyTransaction(db),
            SqlRepositoryStore(db),
            GitRepository(
                app.state.settings.project_repository_directory,
                UUID(project_id),
                app.state.settings.project_repository_max_bytes,
            ),
            UUID(project_id),
            first.requested_by_user_id,
        )
        binding = service.pin_run(first.id, first.conversation_id)
        assert binding is not None
        assert binding["branch"] == task["branch"]
        assert binding["worktree_id"] == task["id"]
        assert binding["revision"] == task["revision"]
        stored = SqlRepositoryStore(db).run(first.id)
        assert stored is not None and stored.branch == task["branch"]
        request_cancel(db, run_id=first.id)
        first = db.get(SqlAgentRun, first.id)
        assert first is not None
        first.status = AgentRunStatus.CANCELLED
        db.commit()
        second = claim_next_run(db, worker_id="worker-two", lease_for=timedelta(minutes=1))
        assert second is not None and str(second.id) == runs[1]["id"]
        resumed = resume_run(
            db,
            run_id=first.id,
            requested_by_user_id=first.requested_by_user_id,
            provider_connection_id=first.provider_connection_id,
            client_request_id=uuid4(),
        )
        assert resumed.conversation_id == first.conversation_id
        assert claim_next_run(db, worker_id="worker-three", lease_for=timedelta(minutes=1)) is None
        request_cancel(db, run_id=resumed.id)
        _, old_intent = append_user_message_and_queue_run(
            db,
            conversation_id=first.conversation_id,
            requested_by_user_id=first.requested_by_user_id,
            provider_connection_id=first.provider_connection_id,
            content_md="Old-timestamp intent",
            client_request_id=uuid4(),
            now=utc_now() - timedelta(hours=1),
        )
        old_intent.created_at = second.created_at - timedelta(hours=1)
        db.commit()
        assert old_intent.created_at < second.created_at
        assert claim_next_run(db, worker_id="worker-three", lease_for=timedelta(minutes=1)) is None


def test_task_disabled_and_foreign_attachment(client: TestClient, tmp_path: Path) -> None:
    project_id = str(create_project(client)["id"])
    url = f"/api/v1/projects/{project_id}/worktrees"
    assert (
        client.post(
            url,
            headers=headers("owner"),
            json={
                "title": "Files",
                "client_request_id": str(uuid4()),
                "branch": "files",
            },
        ).status_code
        == 503
    )
    cast(FastAPI, client.app).state.settings.project_repository_directory = tmp_path / "repos"
    task = create_task(client, project_id)
    other = str(create_project(client)["id"])
    assert (
        client.post(
            "/api/v1/conversations",
            headers=headers("owner"),
            json={
                "project_id": other,
                "worktree_id": task["id"],
                "agent_kind": "RESEARCHER",
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/projects/{other}/worktrees",
            headers=headers("owner"),
            json={
                "title": task["title"],
                "client_request_id": task["id"],
                "branch": task["branch"],
            },
        ).status_code
        == 404
    )


def test_sqlite_task_migration_preserves_legacy_working_copies_and_private_titles(
    tmp_path: Path,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    from polycolab.operations.local_development import MIGRATIONS, upgrade_database

    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{path}")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    sid = uuid4().hex
    uid = uuid4().hex
    wid = uuid4().hex
    aid = uuid4().hex
    with engine.begin() as db:
        config.attributes["connection"] = db
        command.upgrade(config, "local_20261006_workspace_files")
        db.exec_driver_sql(
            "INSERT INTO users "
            "(id,issuer,subject,email,display_name,created_at,updated_at) VALUES (?,?,? "
            ",?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            (uid, "test", "owner", "owner@test", "Owner"),
        )
        db.exec_driver_sql(
            "INSERT INTO projects "
            "(id,name,description,visibility,created_by_user_id,created_at,updated_at) "
            "VALUES (?,?,?,'PRIVATE',?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            (wid, "Task project", "", uid),
        )
        db.exec_driver_sql(
            "INSERT INTO platform_agent_versions "
            "(id,agent_kind,version,display_name,instructions_text,instructions_digest,e"
            "xecution_profile,created_at) VALUES "
            "(?,'RESEARCHER',1,'Researcher','instructions',?,'TRUSTED_HOSTED',CURRENT_TI"
            "MESTAMP)",
            (aid, uuid4().hex),
        )
        db.exec_driver_sql(
            "INSERT INTO agent_sessions "
            "(id,project_id,agent_version_id,created_by_user_id,title,status,next_messag"
            "e_sequence,next_run_sequence,created_at,updated_at) VALUES "
            "(?,?,?,?,'Private secret','ACTIVE',0,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            (sid, wid, aid, uid),
        )
        db.exec_driver_sql(
            "INSERT INTO workspace_repositories (workspace_id,created_at) "
            "VALUES (?,CURRENT_TIMESTAMP)",
            (wid,),
        )
        db.exec_driver_sql(
            "INSERT INTO repository_sessions (session_id,workspace_id,base_commit) VALUES (?,?,?)",
            (sid, wid, "a" * 40),
        )
    engine.dispose()
    assert upgrade_database(path) is not None
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as db:
            row = db.exec_driver_sql("SELECT id,title,branch FROM worktrees").one()
            assert row == (sid, "Saved agent working copy", f"sessions/{UUID(sid)}")
            assert db.exec_driver_sql("SELECT worktree_id,title FROM conversations").one() == (
                sid,
                "Private secret",
            )
    finally:
        engine.dispose()
