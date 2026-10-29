"""Forward-only removal of the retired research schema, preserving workspace state."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

RETIRED_TABLES = (
    "artifact_research_links",
    "catalogue_audit",
    "catalogue_entries",
    "catalogue_follows",
    "catalogue_interest",
    "catalogue_moderator_audit",
    "catalogue_moderators",
    "catalogue_revisions",
    "community_delivery_cursors",
    "contribution_entity_links",
    "contribution_envelopes",
    "correction_decisions",
    "correction_suggestions",
    "correspondence_assessments",
    "external_research_runs",
    "external_run_invocations",
    "human_note_revisions",
    "human_notes",
    "object_reviews",
    "object_revisions",
    "object_version_relationships",
    "outbox_consumer_receipts",
    "outbox_events",
    "project_reference_versions",
    "project_references",
    "proof_sketch_revisions",
    "proposal_change_decisions",
    "proposal_changes",
    "proposal_decision_batches",
    "proposals",
    "public_releases",
    "public_research_anchors",
    "publication_artifact_members",
    "publication_comments",
    "publication_manifests",
    "publication_progress",
    "publication_relations",
    "publication_reviews",
    "publication_revisions",
    "publication_summaries",
    "record_moderation",
    "record_moderation_audit",
    "record_revisions",
    "research_activity_events",
    "research_attempt_revisions",
    "research_comments",
    "research_notifications",
    "research_objects",
    "research_progress_summaries",
    "research_progress_updates",
    "research_scopes",
    "research_submission_counter",
    "research_summaries",
    "research_summary_revisions",
    "review_evidence",
    "revision_endorsements",
    "run_artifact_outputs",
    "run_revision_outputs",
    "run_write_grants",
    "statement_revisions",
    "summary_source_revisions",
    "verification_attempts",
    "verification_environments",
    "verification_events",
    "verification_inputs",
    "verification_jobs",
    "verification_output_artifacts",
    "verification_reservations",
    "verification_results",
)

CHANGED_TABLES = (
    "artifacts",
    "context_manifests",
    "external_agent_credentials",
    "execution_slot_leases",
    "execution_work_items",
    "execution_fairness_states",
    "execution_class_states",
    "context_manifest_artifacts",
)


def _remove_columns(table: str, columns: tuple[str, ...], checks: tuple[str, ...] = ()) -> None:
    if op.get_bind().dialect.name == "postgresql":
        # PostgreSQL drops column-local checks, indexes and constraints with the column.
        for column in columns:
            op.drop_column(table, column)
        return
    inspector = sa.inspect(op.get_bind())
    convention = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table(table, naming_convention=convention) as batch:
        for fk in inspector.get_foreign_keys(table):
            if set(fk["constrained_columns"]) & set(columns):
                name = (
                    fk["name"]
                    or f"fk_{table}_{fk['constrained_columns'][0]}_{fk['referred_table']}"
                )
                batch.drop_constraint(name, type_="foreignkey")
        for unique in inspector.get_unique_constraints(table):
            if set(unique["column_names"]) & set(columns) and unique["name"]:
                batch.drop_constraint(unique["name"], type_="unique")
        for index in inspector.get_indexes(table):
            if set(index["column_names"]) & set(columns) and index["name"] is not None:
                batch.drop_index(index["name"])
        for name in checks:
            batch.drop_constraint(name, type_="check")
        for column in columns:
            batch.drop_column(column)


def _cancel_retired_grant_runs() -> None:
    """Never reinterpret a restricted research intent as full conversation access."""
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        # Keep the PostgreSQL upgrade usable in Alembic's offline SQL mode too.
        op.execute("""WITH cancelled AS (
            UPDATE agent_runs SET status='CANCELLED',
                cancel_requested_at=COALESCE(cancel_requested_at, CURRENT_TIMESTAMP),
                finished_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP,
                failure_code='research_authority_retired',
                next_event_cursor=next_event_cursor+1,
                lease_generation=lease_generation+1, lease_owner=NULL, lease_expires_at=NULL
            WHERE status IN ('QUEUED', 'CLAIMED', 'RUNNING', 'CANCELLING')
              AND id IN (SELECT run_id FROM run_write_grants)
            RETURNING id, next_event_cursor
        ) INSERT INTO agent_run_events
            (id, run_id, cursor, idempotency_key, kind, payload, occurred_at, created_at)
          SELECT gen_random_uuid(), id, next_event_cursor, 'workspace-only-grant-retired',
            'RUN_CANCELLED', '{"code":"research_authority_retired"}'::json,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM cancelled""")
        return
    metadata = sa.MetaData()
    runs = sa.Table("agent_runs", metadata, autoload_with=connection)
    grants = sa.Table("run_write_grants", metadata, autoload_with=connection)
    events = sa.Table("agent_run_events", metadata, autoload_with=connection)
    now = datetime.now(UTC)
    affected = connection.execute(
        sa.select(runs.c.id, runs.c.next_event_cursor, runs.c.lease_generation).where(
            runs.c.id.in_(sa.select(grants.c.run_id)),
            runs.c.status.in_(("QUEUED", "CLAIMED", "RUNNING", "CANCELLING")),
        )
    ).all()
    for run in affected:
        cursor = run.next_event_cursor + 1
        event_id = uuid4()
        connection.execute(
            events.insert().values(
                id=event_id if connection.dialect.name == "postgresql" else event_id.hex,
                run_id=run.id,
                cursor=cursor,
                idempotency_key="workspace-only-grant-retired",
                kind="RUN_CANCELLED",
                payload={"code": "research_authority_retired"},
                occurred_at=now,
                created_at=now,
            )
        )
        connection.execute(
            runs.update()
            .where(runs.c.id == run.id)
            .values(
                status="CANCELLED",
                cancel_requested_at=sa.func.coalesce(runs.c.cancel_requested_at, now),
                finished_at=now,
                updated_at=now,
                failure_code="research_authority_retired",
                next_event_cursor=cursor,
                lease_generation=run.lease_generation + 1,
                lease_owner=None,
                lease_expires_at=None,
            )
        )


def upgrade() -> None:
    connection = op.get_bind()
    postgres = connection.dialect.name == "postgresql"
    _cancel_retired_grant_runs()
    if postgres:
        table_literals = ",".join("'" + name + "'" for name in RETIRED_TABLES)
        op.execute(
            "CREATE TEMP TABLE retired_trigger_functions ON COMMIT DROP AS "
            "SELECT DISTINCT t.tgfoid AS oid, t.tgfoid::regprocedure::text AS signature "
            "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=current_schema() AND NOT t.tgisinternal "
            f"AND c.relname IN ({table_literals})"
        )
        for table in CHANGED_TABLES:
            op.execute(f'ALTER TABLE "{table}" DISABLE TRIGGER USER')
        op.execute("DROP TRIGGER artifacts_destination_immutable ON artifacts")
        op.execute("DROP FUNCTION protect_artifact_destination()")

    with op.batch_alter_table("artifacts") as batch:
        batch.add_column(sa.Column("project_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_artifacts_project", "projects", ["project_id"], ["id"])
        batch.create_index("ix_artifacts_project_id", ["project_id"])
    op.execute(
        "UPDATE artifacts SET project_id = (SELECT project_id FROM research_scopes "
        "WHERE research_scopes.id = artifacts.ownership_scope_id)"
    )
    # Keep byte identities discoverable by GC; SQL migrations never delete object storage.
    op.execute(
        "UPDATE artifacts SET state='DELETING', committed_at=NULL, deleted_at=NULL, "
        "expires_at=CURRENT_TIMESTAMP WHERE project_id IS NULL AND state <> 'DELETED'"
    )
    op.execute("UPDATE run_tool_capabilities SET revoked=true")
    op.execute("UPDATE external_agent_credentials SET fixed_rights='[\"PROJECT_WRITE\"]'")
    if postgres:
        # UUID-only JSON pins have the same canonical representation as Python's digest.
        op.execute("""UPDATE context_manifests SET digest = encode(sha256(convert_to(
            '{"artifact_ids":' || replace(artifact_ids::text, ' ', '') || ',"version":' || '3}',
            'UTF8')), 'hex')""")
    else:
        manifests = sa.Table("context_manifests", sa.MetaData(), autoload_with=connection)
        for row in connection.execute(sa.select(manifests.c.id, manifests.c.artifact_ids)):
            digest = hashlib.sha256(
                json.dumps(
                    {"version": 3, "artifact_ids": row.artifact_ids},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            connection.execute(
                manifests.update().where(manifests.c.id == row.id).values(digest=digest)
            )

    for table in (
        "execution_slot_leases",
        "execution_work_items",
        "execution_fairness_states",
        "execution_class_states",
    ):
        op.execute(f"DELETE FROM {table} WHERE workload_class <> 'AGENT'")
    if postgres:
        # Remove only foreign keys from retained tables into the explicitly retired set.
        op.execute(f"""DO $$ DECLARE edge RECORD; BEGIN
          FOR edge IN SELECT con.conname, con.conrelid::regclass AS source
            FROM pg_constraint con JOIN pg_class target ON target.oid=con.confrelid
            JOIN pg_namespace ns ON ns.oid=target.relnamespace
            JOIN pg_class source ON source.oid=con.conrelid
            WHERE con.contype='f' AND ns.nspname=current_schema()
              AND target.relname IN ({table_literals})
              AND source.relname NOT IN ({table_literals})
          LOOP EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', edge.source, edge.conname);
          END LOOP;
        END $$""")
        op.execute("DROP VIEW IF EXISTS relation_assertions")
        op.execute("DROP TABLE " + ", ".join('"' + name + '"' for name in RETIRED_TABLES))

    _remove_columns(
        "artifacts",
        (
            "ownership_scope_id",
            "contribution_id",
            "source_revision_id",
            "library_destination_revision_id",
        ),
    )
    _remove_columns("agent_runs", ("requested_context_revision_ids",))
    _remove_columns("context_manifests", ("revision_ids",))
    _remove_columns("external_agent_credentials", ("allow_reviews", "allow_library_contributions"))
    _remove_columns(
        "execution_work_items",
        ("verification_job_id", "verification_cpu_seconds", "verification_memory_byte_seconds"),
        (
            "ck_execution_work_item_identity",
            "ck_execution_work_item_resource_shape",
            "ck_execution_work_item_verification_cpu",
            "ck_execution_work_item_verification_memory",
        ),
    )
    _remove_columns(
        "execution_slot_leases", ("verification_attempt_id",), ("ck_execution_slot_identity",)
    )
    for table, check in (
        ("execution_work_items", "ck_execution_work_item_class"),
        ("execution_slot_leases", "ck_execution_slot_class"),
        ("execution_class_states", "ck_execution_class_name"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(check, type_="check")
            batch.create_check_constraint(check, "workload_class = 'AGENT'")

    if postgres:
        from polycolab.db.migrations.workspace_triggers import restore_triggers

        restore_triggers()
        for table in CHANGED_TABLES:
            op.execute(f'ALTER TABLE "{table}" ENABLE TRIGGER USER')
        op.execute("""DO $$ DECLARE fn RECORD; BEGIN
          FOR fn IN SELECT * FROM retired_trigger_functions LOOP
            IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgfoid=fn.oid) THEN
              EXECUTE 'DROP FUNCTION ' || fn.signature;
            END IF;
          END LOOP;
        END $$""")
    else:
        # The SQLite migration runner holds BEGIN IMMEDIATE with foreign keys disabled.
        for table in RETIRED_TABLES:
            op.drop_table(table)


def downgrade() -> None:
    raise RuntimeError("Research removal discards retired data; restore a backup to roll back.")
