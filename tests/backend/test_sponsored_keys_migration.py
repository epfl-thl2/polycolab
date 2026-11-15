"""Populated upgrades retain key authority and encryption without identity rows."""

from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from polycolab.agents.credentials import (
    ExternalAgentInvalid,
    _digest,
    credential_from_secret,
)
from polycolab.agents.external import key_secret_context, reveal_credential
from polycolab.db.base import Base
from polycolab.entities.time import utc_now
from polycolab.model_gateway.credentials import (
    LocalAesGcmKeyWrapper,
    encrypt_credential,
)
from polycolab.operations.local_development import MIGRATIONS, upgrade_database

WRAPPER = LocalAesGcmKeyWrapper(b"m" * 32)


def populate(
    connection: Connection,
) -> tuple[UUID, list[tuple[UUID, str, dict[str, Any]]]]:
    metadata = sa.MetaData()
    metadata.reflect(connection)
    user, identity = uuid4(), uuid4()
    now = utc_now()

    def key(value: UUID) -> UUID | str:
        return value.hex if connection.dialect.name == "sqlite" else value

    connection.execute(
        metadata.tables["users"]
        .insert()
        .values(
            id=key(user),
            issuer="migration",
            subject="sponsor",
            created_at=now,
            updated_at=now,
        )
    )
    connection.execute(
        metadata.tables["external_agent_identities"]
        .insert()
        .values(
            id=key(identity),
            sponsor_user_id=key(user),
            name="Old identity",
            created_at=now,
        )
    )
    credentials = metadata.tables["external_agent_credentials"]
    result = []
    for index in range(4):
        identifier = uuid4()
        secret = f"pca_{identifier.hex}_migration-only-{index}"
        encrypted = encrypt_credential(
            WRAPPER, context=key_secret_context(user, identifier), secret=secret
        )
        connection.execute(
            credentials.insert().values(
                id=key(identifier),
                sponsor_user_id=key(user),
                agent_id=key(identity) if index != 3 else None,
                name=f"Preserved key {index}",
                scope_kind="ACCOUNT",
                token_digest=_digest(secret),
                encrypted_secret=encrypted.ciphertext,
                wrapped_data_key=encrypted.wrapped_key,
                encryption_key_version=encrypted.key_version,
                fixed_rights=["PROJECT_WRITE"],
                expires_at=now + timedelta(days=-1 if index == 2 else 1),
                revoked_at=now if index == 1 else None,
                request_count=7,
                mutation_count=2,
                max_requests=100,
                max_mutations=10,
                created_at=now,
            )
        )
        before = dict(
            connection.execute(sa.select(credentials).where(credentials.c.id == key(identifier)))
            .mappings()
            .one()
        )
        before.pop("agent_id")
        result.append((identifier, secret, before))
    return user, result


def verify(
    connection: Connection, data: tuple[UUID, list[tuple[UUID, str, dict[str, Any]]]]
) -> None:
    user, credentials = data
    inspector = sa.inspect(connection)
    assert "external_agent_identities" not in inspector.get_table_names()
    assert "agent_id" not in {c["name"] for c in inspector.get_columns("agent_api_keys")}
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    assert not compare_metadata(MigrationContext.configure(connection), Base.metadata)
    table = sa.Table("agent_api_keys", sa.MetaData(), autoload_with=connection)
    for index, (identifier, secret, before) in enumerate(credentials):
        stored_id = identifier.hex if connection.dialect.name == "sqlite" else identifier
        after = dict(
            connection.execute(sa.select(table).where(table.c.id == stored_id)).mappings().one()
        )
        assert after == {
            {
                "sponsor_user_id": "owner_user_id",
                "mutation_count": "write_count",
                "max_mutations": "max_writes",
            }.get(k, k): v
            for k, v in before.items()
        }
        with Session(connection, join_transaction_mode="create_savepoint") as session:
            if index in (1, 2):
                with pytest.raises(ExternalAgentInvalid):
                    credential_from_secret(session, secret, consume_request=False)
            else:
                credential = credential_from_secret(session, secret, consume_request=False)
                assert credential.id == identifier
                assert credential.owner_user_id == user
                assert (
                    reveal_credential(
                        session, credential_id=identifier, user_id=user, wrapper=WRAPPER
                    )
                    == secret
                )
    if connection.dialect.name == "sqlite":
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    else:
        # Grant immutability must survive replacing the trigger's identity binding.
        with pytest.raises(sa.exc.DBAPIError, match="API key grant is immutable"):
            with connection.begin_nested():
                connection.execute(table.update().values(max_writes=999))


def test_sqlite_upgrade_preserves_sponsored_keys(tmp_path: Path) -> None:
    path = tmp_path / "keys.db"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "local_20261103_session_workspace")
        data = populate(connection)
    upgrade_database(path)
    with engine.connect() as connection:
        verify(connection, data)
    engine.dispose()


def test_postgresql_upgrade_preserves_sponsored_keys(pg_schema: Any) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "20261103_session_workspace")
    with engine.begin() as connection:
        data = populate(connection)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        verify(connection, data)


def test_retired_identity_paths_and_fields_are_rejected(client: TestClient) -> None:
    headers = {"Authorization": "Bearer owner"}
    root = "/api/v1/account/agents"
    for method, path in (("GET", root), ("POST", root), ("PATCH", f"{root}/{uuid4()}")):
        assert (
            client.request(method, path, headers=headers, json={"name": "retired"}).status_code
            == 404
        )
    response = client.post(
        "/api/v1/account/agent-keys",
        headers=headers,
        json={"name": "obsolete binding", "agent_id": str(uuid4())},
    )
    assert response.status_code == 422
    created = client.post("/api/v1/account/agent-keys", headers=headers, json={"name": "Named key"})
    assert created.status_code == 201
    assert "agent_id" not in created.json()
    assert "owner_user_id" in created.json()
    assert created.json()["write_count"] == 0
    assert created.json()["max_writes"] > 0
    assert not {"sponsor_user_id", "mutation_count", "max_mutations"} & created.json().keys()
    identity = client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {created.json()['secret']}"}
    )
    assert identity.status_code == 200
    assert identity.json()["credential_id"] == created.json()["id"]
    assert "agent_id" not in identity.json()
    assert identity.json()["writes_remaining"] == created.json()["max_writes"]
    assert "mutations_remaining" not in identity.json()
