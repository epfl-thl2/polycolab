"""Populated upgrades discard research while preserving workspace-owned state."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from polycolab.agents.sessions import (
    LeaseLost,
    claim_next_run_in_transaction,
    start_claimed_run,
)

from polycolab.db.base import Base
from polycolab.entities.time import utc_now
from polycolab.operations.local_development import MIGRATIONS, upgrade_database


def populate(connection: Connection) -> dict[str, Any]:
    metadata = sa.MetaData()
    metadata.reflect(connection)
    now = utc_now()
    user, project, scope, contribution, artifact, key, agent, session, message = (
        uuid4() for _ in range(9)
    )

    def insert(table_name: str, **values: Any) -> None:
        if connection.dialect.name == "sqlite":
            values = {
                k: v.hex if isinstance(v, type(user)) else v for k, v in values.items()
            }
        connection.execute(metadata.tables[table_name].insert().values(**values))

    insert(
        "users",
        id=user,
        issuer="migration",
        subject="owner",
        created_at=now,
        updated_at=now,
    )
    insert(
        "projects",
        id=project,
        name="Workspace to keep",
        visibility="PRIVATE",
        workspace_mode="default",
        created_by_user_id=user,
        created_at=now,
        updated_at=now,
    )
    insert(
        "memberships",
        id=uuid4(),
        project_id=project,
        user_id=user,
        role="OWNER",
        created_at=now,
        updated_at=now,
    )
    insert(
        "research_scopes",
        id=scope,
        project_id=project,
        scope_kind="PROJECT",
        created_at=now,
    )
    insert(
        "contribution_envelopes",
        id=contribution,
        actor_kind="HUMAN",
        human_user_id=user,
        ownership_scope_id=scope,
        project_id=project,
        operation="artifact.stage",
        source_event_cursors=[],
        created_at=now,
    )
    insert(
        "artifacts",
        id=artifact,
        ownership_scope_id=scope,
        contribution_id=contribution,
        created_by_user_id=user,
        sha256=hashlib.sha256(b"keep bytes").hexdigest(),
        byte_length=10,
        media_type="text/plain",
        storage_key="staging/retained",
        state="COMMITTED",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        verified_at=now,
        committed_at=now,
    )
    insert(
        "external_agent_credentials",
        id=key,
        scope_kind="ACCOUNT",
        sponsor_user_id=user,
        allow_library_contributions=False,
        name="Keep key",
        token_digest="a" * 64,
        fixed_rights=[
            "PROJECT_WRITE",
            "CONTRIBUTION_CREATE",
            "CONTRIBUTION_EDIT",
            "PUBLIC_PARTICIPATION",
        ],
        expires_at=now + timedelta(days=1),
        request_count=7,
        mutation_count=2,
        max_requests=100,
        max_mutations=10,
        created_at=now,
        encrypted_secret=b"keep ciphertext",
        wrapped_data_key=b"keep wrapped key",
        encryption_key_version="keep version",
    )
    insert(
        "platform_agent_versions",
        id=agent,
        agent_kind="RESEARCHER",
        version=99,
        display_name="Keep agent",
        instructions_text="Work with files",
        instructions_digest="c" * 64,
        execution_profile="TRUSTED_HOSTED",
        created_at=now,
    )
    insert(
        "agent_sessions",
        id=session,
        project_id=project,
        agent_version_id=agent,
        created_by_user_id=user,
        status="ACTIVE",
        next_message_sequence=1,
        next_run_sequence=0,
        created_at=now,
        updated_at=now,
    )
    insert(
        "agent_messages",
        id=message,
        session_id=session,
        sequence=1,
        role="USER",
        author_user_id=user,
        content_md="Keep this conversation",
        created_at=now,
    )
    profile, run, manifest, capability = (uuid4() for _ in range(4))
    insert(
        "gateway_profiles",
        id=profile,
        user_id=user,
        display_name="Keep provider",
        base_url="https://provider.example/v1",
        model_id="test-model",
        wire_api="responses",
        credential_version=1,
        encrypted_credential=b"keep provider ciphertext",
        wrapped_data_key=b"keep provider key",
        encryption_key_version="keep provider version",
        created_at=now,
        updated_at=now,
    )
    insert(
        "agent_runs",
        id=run,
        session_id=session,
        project_id=project,
        agent_version_id=agent,
        requested_by_user_id=user,
        request_message_id=message,
        client_request_id=uuid4(),
        gateway_profile_id=profile,
        gateway_credential_version=1,
        gateway_model_id="test-model",
        queue_sequence=1,
        input_message_sequence=1,
        requested_context_revision_ids=[str(uuid4())],
        requested_context_artifact_ids=[str(artifact)],
        status="COMPLETED",
        attempt=1,
        lease_generation=1,
        next_event_cursor=0,
        created_at=now,
        updated_at=now,
    )
    insert(
        "context_manifests",
        id=manifest,
        run_id=run,
        project_id=project,
        requested_by_user_id=user,
        agent_version_id=agent,
        revision_ids=[str(uuid4())],
        artifact_ids=[str(artifact)],
        digest="d" * 64,
        created_at=now,
    )
    insert(
        "context_manifest_artifacts",
        manifest_id=manifest,
        artifact_id=artifact,
        position=0,
    )
    insert(
        "run_tool_capabilities",
        id=capability,
        token_digest="e" * 64,
        run_id=run,
        session_id=session,
        project_id=project,
        user_id=user,
        agent_version_id=agent,
        context_manifest_id=manifest,
        allowed_tools=["get_context", "submit_proposal"],
        lease_generation=1,
        expires_at=now + timedelta(hours=1),
        revoked=False,
        created_at=now,
    )
    restricted_runs = []
    for sequence, status in enumerate(
        ("QUEUED", "CLAIMED", "RUNNING", "CANCELLING", "COMPLETED"), start=2
    ):
        restricted = uuid4()
        original = dict(
            connection.execute(
                sa.select(metadata.tables["agent_runs"]).where(
                    metadata.tables["agent_runs"].c.id
                    == (run.hex if connection.dialect.name == "sqlite" else run)
                )
            )
            .mappings()
            .one()
        )
        original.update(
            id=restricted,
            request_message_id=None,
            client_request_id=uuid4(),
            queue_sequence=sequence,
            status=status,
            next_event_cursor=1,
            lease_owner="old-worker",
            lease_generation=7,
            lease_expires_at=now + timedelta(hours=1),
        )
        insert("agent_runs", **original)
        insert(
            "run_write_grants",
            run_id=restricted,
            request={"public_task": "Only this authorized public task"},
            request_digest="f" * 64,
            created_at=now,
        )
        insert(
            "agent_run_events",
            id=uuid4(),
            run_id=restricted,
            cursor=1,
            idempotency_key="existing-event",
            kind="CANCEL_REQUESTED",
            payload={},
            occurred_at=now,
            created_at=now,
        )
        restricted_runs.append((restricted, status))
    ungranted = uuid4()
    original.update(
        id=ungranted,
        client_request_id=uuid4(),
        queue_sequence=7,
        status="QUEUED",
        next_event_cursor=0,
    )
    insert("agent_runs", **original)
    commons = connection.scalar(
        sa.select(metadata.tables["research_scopes"].c.id).where(
            metadata.tables["research_scopes"].c.scope_kind == "COMMONS"
        )
    )
    common_contribution, orphan = uuid4(), uuid4()
    insert(
        "contribution_envelopes",
        id=common_contribution,
        actor_kind="HUMAN",
        human_user_id=user,
        ownership_scope_id=commons,
        operation="artifact.stage",
        source_event_cursors=[],
        created_at=now,
    )
    insert(
        "artifacts",
        id=orphan,
        ownership_scope_id=commons,
        contribution_id=common_contribution,
        created_by_user_id=user,
        sha256="b" * 64,
        byte_length=1,
        media_type="text/plain",
        storage_key="staging/retired",
        state="COMMITTED",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        verified_at=now,
        committed_at=now,
    )
    return {
        "restricted_runs": restricted_runs,
        "ungranted": ungranted,
        "project": project,
        "artifact": artifact,
        "orphan": orphan,
        "key": key,
        "message": message,
        "profile": profile,
        "manifest": manifest,
        "capability": capability,
    }


def verify(connection: Connection, ids: dict[str, Any]) -> None:
    inspector = sa.inspect(connection)
    names = set(inspector.get_table_names())
    assert names == set(Base.metadata.tables) | {"alembic_version"}
    assert not compare_metadata(MigrationContext.configure(connection), Base.metadata)
    metadata = sa.MetaData()
    metadata.reflect(connection)

    def key(name: str) -> Any:
        return ids[name].hex if connection.dialect.name == "sqlite" else ids[name]

    runs = metadata.tables["agent_runs"]
    events = metadata.tables["agent_run_events"]
    for run_id, previous_status in ids["restricted_runs"]:
        stored_id = run_id.hex if connection.dialect.name == "sqlite" else run_id
        run = connection.execute(sa.select(runs).where(runs.c.id == stored_id)).one()
        if previous_status == "COMPLETED":
            assert run.status == "COMPLETED" and run.next_event_cursor == 1
            continue
        assert run.status == "CANCELLED"
        assert run.cancel_requested_at is not None and run.finished_at is not None
        assert run.failure_code == "research_authority_retired"
        assert run.lease_owner is None and run.lease_expires_at is None
        assert run.lease_generation == 8 and run.next_event_cursor == 2
        history = connection.execute(
            sa.select(events)
            .where(events.c.run_id == stored_id)
            .order_by(events.c.cursor)
        ).all()
        assert len(history) == 2
        assert history[0].idempotency_key == "existing-event"
        assert history[1].kind == "RUN_CANCELLED"
        assert history[1].payload == {"code": "research_authority_retired"}
        with Session(connection, join_transaction_mode="create_savepoint") as session:
            assert (
                claim_next_run_in_transaction(
                    session,
                    worker_id="new-worker",
                    lease_for=timedelta(minutes=1),
                    run_id=run_id,
                )
                is None
            )
            with pytest.raises(LeaseLost):
                start_claimed_run(
                    session, run_id=run_id, worker_id="old-worker", lease_generation=7
                )
    assert (
        connection.scalar(sa.select(runs.c.status).where(runs.c.id == key("ungranted")))
        == "QUEUED"
    )
    artifacts = metadata.tables["artifacts"]
    saved = connection.execute(
        sa.select(artifacts).where(artifacts.c.id == key("artifact"))
    ).one()
    assert saved.project_id == key("project") and saved.state == "COMMITTED"
    assert saved.storage_key == "staging/retained" and saved.byte_length == 10
    orphan = connection.execute(
        sa.select(artifacts).where(artifacts.c.id == key("orphan"))
    ).one()
    assert (
        orphan.project_id is None
        and orphan.state == "DELETING"
        and orphan.committed_at is None
    )
    credentials = metadata.tables["external_agent_credentials"]
    credential = connection.execute(
        sa.select(credentials).where(credentials.c.id == key("key"))
    ).one()
    assert credential.token_digest == "a" * 64 and credential.fixed_rights == [
        "PROJECT_WRITE"
    ]
    assert credential.encrypted_secret == b"keep ciphertext"
    assert credential.request_count == 7 and credential.mutation_count == 2
    messages = metadata.tables["agent_messages"]
    assert (
        connection.scalar(
            sa.select(messages.c.content_md).where(messages.c.id == key("message"))
        )
        == "Keep this conversation"
    )
    profiles = metadata.tables["gateway_profiles"]
    assert (
        connection.scalar(
            sa.select(profiles.c.encrypted_credential).where(
                profiles.c.id == key("profile")
            )
        )
        == b"keep provider ciphertext"
    )
    manifests = metadata.tables["context_manifests"]
    context = connection.execute(
        sa.select(manifests).where(manifests.c.id == key("manifest"))
    ).one()
    assert context.artifact_ids == [str(ids["artifact"])]
    assert (
        context.digest
        == hashlib.sha256(
            json.dumps(
                {"artifact_ids": context.artifact_ids, "version": 3},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    capabilities = metadata.tables["run_tool_capabilities"]
    assert (
        connection.scalar(
            sa.select(capabilities.c.revoked).where(
                capabilities.c.id == key("capability")
            )
        )
        is True
    )


def test_populated_sqlite_upgrade(tmp_path: Path) -> None:
    path = tmp_path / "workspace.db"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "local_20261028_chat_latex")
        ids = populate(connection)
    workspace_file = tmp_path / "project.txt"
    workspace_file.write_bytes(b"keep workspace file")
    upgrade_database(path)
    with engine.connect() as connection:
        verify(connection, ids)
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    assert workspace_file.read_bytes() == b"keep workspace file"
    assert upgrade_database(path) is None
    engine.dispose()


def test_populated_postgresql_upgrade(pg_schema: Any) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "20261028_chat_latex")
    with engine.begin() as connection:
        ids = populate(connection)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        verify(connection, ids)
