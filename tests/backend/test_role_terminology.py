"""Populated role upgrades preserve membership and invitation authority."""

from datetime import timedelta
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
def test_role_upgrade(request: pytest.FixtureRequest, tmp_path: Path, dialect: str) -> None:
    if dialect == "postgresql":
        engine, config, _ = request.getfixturevalue("pg_schema")
        prefix = ""
    else:
        engine = sa.create_engine(f"sqlite:///{tmp_path / 'roles.db'}")
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS))
        prefix = "local_"
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, prefix + "20261115_provider_connections")
        metadata = sa.MetaData()
        metadata.reflect(connection)
        now = utc_now()

        def key(identifier: UUID) -> UUID | str:
            return identifier.hex if dialect == "sqlite" else identifier

        users = [key(uuid4()) for _ in range(3)]
        for user in users:
            connection.execute(
                metadata.tables["users"]
                .insert()
                .values(
                    id=user, issuer="migration", subject=str(user), created_at=now, updated_at=now
                )
            )
        project = key(uuid4())
        connection.execute(
            metadata.tables["projects"]
            .insert()
            .values(
                id=project,
                name="Retained permissions",
                visibility="PRIVATE",
                workspace_mode="git",
                created_by_user_id=users[0],
                created_at=now,
                updated_at=now,
            )
        )
        expected = {}
        for user, old, new in zip(
            users, ("OWNER", "CONTRIBUTOR", "READ_ONLY"), ("OWNER", "EDITOR", "VIEWER"), strict=True
        ):
            identifier = key(uuid4())
            expected[identifier] = new
            connection.execute(
                metadata.tables["memberships"]
                .insert()
                .values(
                    id=identifier,
                    project_id=project,
                    user_id=user,
                    role=old,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                metadata.tables["invitations"]
                .insert()
                .values(
                    id=identifier,
                    project_id=project,
                    email=f"{user}@example.test",
                    role=old,
                    token_digest=uuid4().hex * 2,
                    invited_by_user_id=users[0],
                    expires_at=now + timedelta(days=1),
                    status="PENDING",
                    created_at=now,
                )
            )
    # PostgreSQL's migration environment opens its own connection. Commit the
    # fixture rows before upgrading so the migration can see existing roles.
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        for name in ("memberships", "invitations"):
            table = metadata.tables[name]
            assert dict(connection.execute(sa.select(table.c.id, table.c.role)).all()) == expected
    if dialect == "sqlite":
        engine.dispose()


@pytest.mark.parametrize("role", ["CONTRIBUTOR", "READ_ONLY"])
def test_old_project_role_values_are_rejected(client: TestClient, role: str) -> None:
    headers = {"Authorization": "Bearer owner"}
    project = client.post("/api/v1/projects", headers=headers, json={"name": "New roles"}).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=headers,
        json={"user_id": str(uuid4()), "role": role},
    )
    assert response.status_code == 422
