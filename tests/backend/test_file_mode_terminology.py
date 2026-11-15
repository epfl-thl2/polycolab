"""Populated vocabulary cutovers retain files, change sets, and retry identities."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from polycolab.entities.time import utc_now
from polycolab.operations.local_development import MIGRATIONS


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
def test_populated_file_mode_upgrade(
    request: pytest.FixtureRequest, tmp_path: Path, dialect: str
) -> None:
    if dialect == "postgresql":
        engine, config, _ = request.getfixturevalue("pg_schema")
        prefix = ""
    else:
        engine = sa.create_engine(f"sqlite:///{tmp_path / 'files.db'}")
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS))
        prefix = "local_"
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, prefix + "20261115_conversation_names")
        metadata = sa.MetaData()
        metadata.reflect(connection)

        def key(identifier: UUID) -> UUID | str:
            return identifier.hex if dialect == "sqlite" else identifier

        def insert(table: str, **values: object) -> None:
            connection.execute(metadata.tables[table].insert().values(**values))

        now = utc_now()
        owner = key(uuid4())
        insert(
            "users",
            id=owner,
            issuer="migration",
            subject=str(owner),
            created_at=now,
            updated_at=now,
        )
        projects = [key(uuid4()) for _ in range(3)]
        for project, mode in zip(projects, ("default", "linear", "git"), strict=True):
            insert(
                "projects",
                id=project,
                name=mode,
                workspace_mode=mode,
                visibility="PRIVATE",
                created_by_user_id=owner,
                created_at=now,
                updated_at=now,
            )
        project = projects[1]
        file_id, change_set_id = key(uuid4()), key(uuid4())
        payload = {"kind": "linear", "batch_id": str(change_set_id)}
        changes = [{"file_id": str(file_id), "base": None, "target": {"path": "notes.txt"}}]
        insert("linear_workspaces", project_id=project, epoch=2, sequence=8, stored_bytes=100)
        insert(
            "linear_files",
            id=file_id,
            project_id=project,
            path="notes.txt",
            content=b"kept",
            document=b"document",
            executable=False,
            deleted=False,
        )
        insert(
            "linear_operations",
            project_id=project,
            sequence=8,
            epoch=2,
            user_id=owner,
            request_key=f"batch:{change_set_id}",
            digest="d" * 64,
            kind="agent",
            payload=payload,
            created_at=now,
        )
        insert(
            "linear_batches",
            id=change_set_id,
            project_id=project,
            user_id=owner,
            epoch=2,
            base_sequence=7,
            status="applied",
            digest="a" * 64,
            changes=changes,
            conflicts=[],
        )
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        current = sa.MetaData()
        current.reflect(connection)
        assert "linear_workspaces" not in current.tables
        assert "linear_batches" not in current.tables
        project_rows = current.tables["projects"]
        assert "workspace_mode" not in project_rows.c
        modes = dict(
            connection.execute(sa.select(project_rows.c.id, project_rows.c.file_mode)).all()
        )
        assert [modes[p] for p in projects] == ["basic", "collaborative", "git"]
        file = connection.execute(sa.select(current.tables["collaborative_files"])).mappings().one()
        assert (file["id"], file["content"], file["document"]) == (file_id, b"kept", b"document")
        operation = (
            connection.execute(sa.select(current.tables["collaborative_operations"]))
            .mappings()
            .one()
        )
        assert operation["request_key"] == f"batch:{change_set_id}"
        assert operation["payload"] == payload
        assert operation["digest"] == "d" * 64
        saved = connection.execute(sa.select(current.tables["change_sets"])).mappings().one()
        assert saved["id"] == change_set_id
        assert saved["changes"] == changes
        assert saved["digest"] == "a" * 64
    if dialect == "sqlite":
        engine.dispose()


@pytest.mark.parametrize("mode", ["default", "linear"])
def test_old_file_mode_values_are_rejected(client: TestClient, mode: str) -> None:
    response = client.post(
        "/api/v1/projects",
        headers={"Authorization": "Bearer owner"},
        json={"name": "Old mode", "file_mode": mode},
    )
    assert response.status_code == 422
