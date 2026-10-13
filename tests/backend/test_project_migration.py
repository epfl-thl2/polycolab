"""Populated forward cutover preserves identities, pinned history and exact bytes."""

from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, insert, inspect, select, text, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentSession,
    SqlContributionEnvelope,
    SqlExecutionClassState,
    SqlExecutionFairnessState,
    SqlExternalAgentCredential,
    SqlGatewayProfile,
    SqlMembership,
    SqlMutationReceipt,
    SqlObjectRevision,
    SqlOutboxEvent,
    SqlPlatformAgentVersion,
    SqlProject,
    SqlRecordRevision,
    SqlResearchObject,
    SqlResearchScope,
    SqlUser,
)
from polycolab.entities.time import utc_now
from polycolab.operations.local_development import MIGRATIONS, upgrade_database
from polycolab.platform.outbox import canonical_digest


def populate(connection: Connection, repository_root: Path) -> None:
    user, project, scope, contribution, obj, version, reference = [uuid4() for _ in range(7)]
    connection.execute(insert(SqlUser).values(id=user, issuer="cutover", subject=str(user)))
    connection.execute(
        insert(SqlProject).values(
            id=project, name="My workspace remains my name", created_by_user_id=user
        )
    )
    connection.execute(insert(SqlMembership).values(project_id=project, user_id=user, role="OWNER"))
    connection.execute(
        insert(SqlResearchScope).values(id=scope, project_id=project, scope_kind="WORKSPACE")
    )
    connection.execute(
        insert(SqlExternalAgentCredential).values(
            project_id=project,
            scope_kind="WORKSPACE",
            sponsor_user_id=user,
            name="Historical key",
            token_digest="a" * 64,
            fixed_rights=["WORKSPACE_WRITE"],
            expires_at=utc_now() + timedelta(days=1),
            max_requests=100,
            max_mutations=10,
        )
    )
    connection.execute(
        insert(SqlContributionEnvelope).values(
            id=contribution,
            actor_kind="HUMAN",
            human_user_id=user,
            ownership_scope_id=scope,
            project_id=project,
            operation="object.create",
        )
    )
    connection.execute(
        insert(SqlResearchObject).values(
            id=obj,
            ownership_scope_id=scope,
            entity_class="RECORD",
            kind="NOTE",
            contribution_id=contribution,
            created_by_user_id=user,
        )
    )
    connection.execute(
        insert(SqlObjectRevision).values(
            id=version,
            object_id=obj,
            ownership_scope_id=scope,
            schema_version=1,
            number=1,
            title="workspace in user text",
            content_md="WORKSPACE is literal research text",
            contribution_id=contribution,
            created_by_user_id=user,
        )
    )
    connection.execute(insert(SqlRecordRevision).values(revision_id=version, kind="NOTE"))
    connection.execute(
        update(SqlResearchObject)
        .where(SqlResearchObject.id == obj)
        .values(current_revision_id=version)
    )
    metadata = MetaData()
    refs = Table("workspace_references", metadata, autoload_with=connection)
    versions = Table("workspace_reference_versions", metadata, autoload_with=connection)

    # Reflected SQLite UUID columns are strings; PostgreSQL UUID columns use UUID objects.
    def key(value: Any) -> Any:
        return value.hex if connection.dialect.name == "sqlite" else value

    connection.execute(
        refs.insert().values(
            id=key(reference),
            project_id=key(project),
            object_id=key(obj),
            created_by_user_id=key(user),
            created_at=utc_now(),
        )
    )
    previous = None
    for number in range(1, 3):
        identity = uuid4()
        connection.execute(
            versions.insert().values(
                id=key(identity),
                reference_id=key(reference),
                number=number,
                base_version_id=key(previous) if previous else None,
                revision_id=key(version),
                created_by_user_id=key(user),
                reason="Historical pin",
                created_at=utc_now(),
            )
        )
        previous = identity
    payload = {"workspace_id": str(project), "message": "workspace user text"}
    connection.execute(
        insert(SqlOutboxEvent).values(
            event_type="workspace.reference.updated",
            aggregate_type="workspace_reference",
            aggregate_id=reference,
            ownership_scope_id=scope,
            payload=payload,
            payload_digest=canonical_digest(payload),
        )
    )
    connection.execute(
        insert(SqlMutationReceipt).values(
            actor_key=f"human:{user}",
            operation="workspace.copy",
            idempotency_key_digest=canonical_digest("prior"),
            request_digest=canonical_digest(payload),
            status="COMMITTED",
            resource_ids=[str(project), str(obj), str(version)],
        )
    )
    if not connection.scalar(
        select(SqlExecutionClassState.workload_class).where(
            SqlExecutionClassState.workload_class == "AGENT"
        )
    ):
        connection.execute(
            insert(SqlExecutionClassState).values(
                workload_class="AGENT",
                active_policy_version=1,
            )
        )
    connection.execute(
        insert(SqlExecutionFairnessState).values(
            workload_class="AGENT",
            tenant_kind="WORKSPACE",
            tenant_id=project,
            policy_version=1,
            virtual_runtime=12345,
        )
    )

    populate_repository(connection, user, project, repository_root)


def populate_repository(connection: Connection, user: UUID, project: UUID, root: Path) -> None:
    from polycolab.projects.git_storage import ZERO, GitRepository
    from polycolab.projects.worktree_storage import WorktreeStorage

    task, agent, session_id, run, gateway = [uuid4() for _ in range(5)]
    branch = f"tasks/{task}"
    git = GitRepository(root, project)
    with git.locked():
        head = git.head("main")
        git.advance(branch, ZERO, head)
        files = WorktreeStorage(git)
        files.initialize(task, branch)
        (files.path(task) / "research.txt").write_text("User workspace notes remain unchanged")

    def key(value: UUID) -> Any:
        return value.hex if connection.dialect.name == "sqlite" else value

    def table(name: str) -> Table:
        return Table(name, MetaData(), autoload_with=connection)

    connection.execute(
        table("workspace_repositories")
        .insert()
        .values(workspace_id=key(project), created_at=utc_now(), native_worktrees=True)
    )
    connection.execute(
        table("workspace_tasks")
        .insert()
        .values(
            id=key(task),
            workspace_id=key(project),
            title="Private workspace task",
            branch=branch,
            created_by_user_id=key(user),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )
    connection.execute(
        insert(SqlPlatformAgentVersion).values(
            id=agent,
            agent_kind="RESEARCHER",
            version=9876,
            display_name="Historical agent",
            instructions_text="Historical workspace instructions",
            instructions_digest="b" * 64,
        )
    )
    connection.execute(
        insert(SqlAgentSession).values(
            id=session_id,
            project_id=project,
            task_id=task,
            agent_version_id=agent,
            created_by_user_id=user,
            title="Private conversation",
        )
    )
    connection.execute(
        insert(SqlGatewayProfile).values(
            id=gateway,
            user_id=user,
            display_name="Fixture",
            base_url="https://example.invalid",
            model_id="fixture",
            encrypted_credential=b"unchanged",
            wrapped_data_key=b"unchanged",
            encryption_key_version="fixture",
            api_key_preview="fixture",
        )
    )
    connection.execute(
        insert(SqlAgentRun).values(
            id=run,
            session_id=session_id,
            project_id=project,
            agent_version_id=agent,
            requested_by_user_id=user,
            gateway_profile_id=gateway,
            gateway_credential_version=1,
            gateway_model_id="fixture",
            queue_sequence=1,
            input_message_sequence=1,
            status="COMPLETED",
        )
    )
    connection.execute(
        table("repository_sessions")
        .insert()
        .values(session_id=key(session_id), workspace_id=key(project), base_commit=head)
    )
    connection.execute(
        table("repository_runs")
        .insert()
        .values(
            run_id=key(run),
            session_id=key(session_id),
            input_commit=head,
            output_commit=head,
            input_revision=head,
            worktree_id=key(task),
            branch=branch,
        )
    )
    connection.execute(
        table("repository_mutations")
        .insert()
        .values(
            id=key(uuid4()),
            workspace_id=key(project),
            user_id=key(user),
            key="pending-save",
            digest=canonical_digest({"historical": "workspace"}),
            branch=branch,
            old_commit=head,
            new_commit=head,
            completed=False,
            created_at=utc_now(),
        )
    )


def repository_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def assert_repository_recovery(engine: Engine, root: Path) -> None:
    from polycolab.db.models import SqlRepositoryMutation
    from polycolab.db.stores.repositories import SqlRepositoryStore
    from polycolab.db.transaction import SqlAlchemyTransaction
    from polycolab.projects.git_storage import GitRepository
    from polycolab.projects.repository_service import RepositoryService

    with Session(engine) as session:
        receipt = session.scalar(select(SqlRepositoryMutation))
        assert receipt is not None
        assert (
            session.scalar(
                select(SqlRepositoryMutation.completed).where(
                    SqlRepositoryMutation.id == receipt.id
                )
            )
            is False
        )
        git = GitRepository(root, receipt.project_id)
        service = RepositoryService(
            SqlAlchemyTransaction(session),
            SqlRepositoryStore(session),
            git,
            receipt.project_id,
            receipt.user_id,
        )
        before = git.head(receipt.branch)
        with service.open():
            assert git.head(receipt.branch) == before
        session.refresh(receipt)
        assert receipt.completed
        assert receipt.digest == canonical_digest({"historical": "workspace"})


TABLES = (
    "users",
    "projects",
    "memberships",
    "research_objects",
    "object_revisions",
    "contribution_envelopes",
    "workspace_references",
    "workspace_reference_versions",
    "workspace_repositories",
    "workspace_tasks",
    "repository_sessions",
    "repository_runs",
    "repository_mutations",
    "agent_sessions",
    "agent_runs",
    "gateway_profiles",
    "outbox_events",
    "mutation_receipts",
)


def snapshot(connection: Connection, *, renamed: bool = False) -> dict[str, list[Any]]:
    # Compare the original identity columns; later migrations add account metadata.
    user_columns = "id, issuer, subject, email, display_name, created_at, updated_at"
    return {
        name: sorted(
            connection.execute(
                text(
                    f"SELECT {user_columns if name == 'users' else '*'} "
                    f"FROM {name.replace('workspace', 'project') if renamed else name}"
                )
            ).all(),
            key=str,
        )
        for name in TABLES
    }


def assert_upgraded(connection: Connection, before: dict[str, list[Any]]) -> None:
    assert snapshot(connection, renamed=True) == before
    inspector = inspect(connection)
    for table in inspector.get_table_names():
        assert "workspace" not in table
        assert all("workspace" not in column["name"] for column in inspector.get_columns(table))
        for collection in (
            inspector.get_indexes(table),
            inspector.get_check_constraints(table),
            inspector.get_unique_constraints(table),
            inspector.get_foreign_keys(table),
        ):
            assert all("workspace" not in (item["name"] or "").lower() for item in collection)
    if connection.dialect.name == "postgresql":
        assert (
            connection.execute(
                text(
                    "SELECT proname FROM pg_proc WHERE pronamespace=current_schema()::regnamespace "
                    "AND prokind='f' AND lower(prosrc) LIKE '%workspace%'"
                )
            ).all()
            == []
        )

    assert (
        connection.scalar(text("SELECT count(*) FROM research_scopes WHERE scope_kind='WORKSPACE'"))
        == 0
    )
    assert connection.execute(
        text("SELECT tenant_kind, virtual_runtime FROM execution_fairness_states")
    ).tuples().all() == [("PROJECT", 12345)]
    credential = connection.execute(
        text("SELECT scope_kind, fixed_rights, token_digest FROM external_agent_credentials")
    ).one()
    assert credential[0] == "PROJECT"
    import json

    rights = json.loads(credential[1]) if isinstance(credential[1], str) else credential[1]
    assert rights == ["WORKSPACE_WRITE"]
    assert credential[2] == "a" * 64
    # Still enforce reference chaining after renaming the tables and PL/pgSQL source.
    refs = Table("project_reference_versions", MetaData(), autoload_with=connection)
    last = connection.execute(select(refs).order_by(refs.c.number.desc())).mappings().first()
    assert last is not None
    identity: Any = uuid4()
    if connection.dialect.name == "sqlite":
        identity = identity.hex
    connection.execute(
        refs.insert().values(
            **{k: v for k, v in last.items() if k not in {"id", "number", "base_version_id"}},
            id=identity,
            number=3,
            base_version_id=last["id"],
        )
    )


def test_sqlite_populated_project_cutover(tmp_path: Path) -> None:
    repository_root = tmp_path / "repositories"
    path = tmp_path / "projects.db"
    engine = create_engine(f"sqlite:///{path}")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "local_20261012_key_preview")
        populate(connection, repository_root)
        before = snapshot(connection)
    git_before = repository_bytes(repository_root)
    assert upgrade_database(path) is not None
    assert repository_bytes(repository_root) == git_before
    with engine.begin() as connection:
        assert_upgraded(connection, before)
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    assert_pending_event(engine, before)
    assert_repository_recovery(engine, repository_root)
    engine.dispose()


def test_postgresql_populated_project_cutover(
    pg_schema: tuple[Engine, Config, str], tmp_path: Path
) -> None:
    repository_root = tmp_path / "repositories"
    engine, config, _ = pg_schema
    command.upgrade(config, "20261012_key_preview")
    with engine.begin() as connection:
        populate(connection, repository_root)
        before = snapshot(connection)
    git_before = repository_bytes(repository_root)
    command.upgrade(config, "head")
    assert repository_bytes(repository_root) == git_before
    with engine.begin() as connection:
        assert_upgraded(connection, before)
    assert_pending_event(engine, before)
    assert_repository_recovery(engine, repository_root)


def assert_pending_event(engine: Engine, before: dict[str, list[Any]]) -> None:
    from polycolab.research.notifications import process_one

    with Session(engine) as session:
        assert process_one(session) is True
        assert process_one(session) is False
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT * FROM outbox_events")).all() == before["outbox_events"]
        )
