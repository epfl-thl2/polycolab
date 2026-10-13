from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_sessions_api import add_member, create_profile, create_project, headers

from polycolab.agents.sessions import (
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
        f"/api/v1/projects/{project_id}/tasks",
        headers=headers("owner"),
        json={"title": title, "client_request_id": str(uuid4())},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def task_chat(
    client: TestClient, project_id: str, task_id: str, token: str = "owner"
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/agent-sessions",
        headers=headers(token),
        json={
            "project_id": project_id,
            "task_id": task_id,
            "agent_kind": "RESEARCHER",
            "title": "Private secret conversation",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_task_working_copy_retry_archive_and_member_privacy(tasks: tuple[TestClient, str]) -> None:
    client, project_id = tasks
    app = cast(FastAPI, client.app)
    app.state.settings.feature_agent_execution_enabled = False
    task = create_task(client, project_id)
    url = f"/api/v1/projects/{project_id}/tasks"
    retry = client.post(
        url,
        headers=headers("owner"),
        json={"title": task["title"], "client_request_id": task["id"]},
    )
    assert retry.status_code == 201
    assert retry.json() == task
    assert client.get(url, headers=headers("owner")).json() == [task]
    repo = client.get(
        f"/api/v1/projects/{project_id}/repository",
        headers=headers("owner"),
        params={"branch": task["branch"]},
    )
    assert repo.status_code == 200, repo.text
    assert repo.json()["writable"]
    app.state.settings.feature_agent_execution_enabled = True
    chat = task_chat(client, project_id, task["id"])
    assert chat["task_id"] == task["id"]
    add_member(client, project_id, "reader", "READ_ONLY")
    assert client.get(url, headers=headers("reader")).json() == [task]
    assert (
        client.get(f"/api/v1/agent-sessions/{chat['id']}", headers=headers("reader")).status_code
        == 403
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
        json={"title": "Updated task", "archived": True},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["archived_at"]
    assert client.get(url, headers=headers("owner")).json() == []
    assert (
        len(client.get(url, headers=headers("owner"), params={"include_archived": True}).json())
        == 1
    )
    assert client.get(f"{url}/{task['id']}", headers=headers("reader")).status_code == 200
    assert not client.get(
        f"/api/v1/projects/{project_id}/repository",
        headers=headers("owner"),
        params={"branch": task["branch"]},
    ).json()["writable"]
    assert (
        client.post(
            "/api/v1/agent-sessions",
            headers=headers("owner"),
            json={"project_id": project_id, "task_id": task["id"], "agent_kind": "RESEARCHER"},
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
    profile = create_profile(client, "owner")
    runs = []
    for chat in chats:
        response = client.post(
            f"/api/v1/agent-sessions/{chat['id']}/messages",
            headers=headers("owner"),
            json={
                "client_request_id": str(uuid4()),
                "content_md": "Work on task",
                "gateway_profile_id": profile["id"],
            },
        )
        assert response.status_code == 202, response.text
        runs.append(response.json()["run"])
    task_url = f"/api/v1/projects/{project_id}/tasks/{task['id']}"
    assert (
        client.patch(task_url, headers=headers("owner"), json={"archived": True}).status_code == 409
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
        binding = service.pin_run(first.id, first.session_id)
        assert binding == {"branch": task["branch"], "commit": state["commit"]}
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
            gateway_profile_id=first.gateway_profile_id,
            client_request_id=uuid4(),
        )
        assert resumed.session_id == first.session_id
        assert claim_next_run(db, worker_id="worker-three", lease_for=timedelta(minutes=1)) is None
        request_cancel(db, run_id=resumed.id)
        _, old_intent = append_user_message_and_queue_run(
            db,
            session_id=first.session_id,
            requested_by_user_id=first.requested_by_user_id,
            gateway_profile_id=first.gateway_profile_id,
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
    url = f"/api/v1/projects/{project_id}/tasks"
    assert (
        client.post(
            url,
            headers=headers("owner"),
            json={"title": "Files", "client_request_id": str(uuid4())},
        ).status_code
        == 409
    )
    cast(FastAPI, client.app).state.settings.project_repository_directory = tmp_path / "repos"
    task = create_task(client, project_id)
    other = str(create_project(client)["id"])
    assert (
        client.post(
            "/api/v1/agent-sessions",
            headers=headers("owner"),
            json={"project_id": other, "task_id": task["id"], "agent_kind": "RESEARCHER"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/projects/{other}/tasks",
            headers=headers("owner"),
            json={"title": task["title"], "client_request_id": task["id"]},
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
            row = db.exec_driver_sql("SELECT id,title,branch FROM project_tasks").one()
            assert row == (sid, "Saved agent working copy", f"sessions/{UUID(sid)}")
            assert db.exec_driver_sql("SELECT task_id,title FROM agent_sessions").one() == (
                sid,
                "Private secret",
            )
    finally:
        engine.dispose()
