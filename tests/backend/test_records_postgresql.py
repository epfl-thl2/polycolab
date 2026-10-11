"""Exercise records and reference history against real migrated PostgreSQL."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from test_community import (
    test_follow_and_interest_are_independent_idempotent_and_private as community_journey,
)
from test_corrections import test_public_correction_edit_accept_and_retry as correction_journey
from test_direct_contributions import active_run
from test_direct_contributions import (
    test_direct_record_retry_and_exact_output_read as direct_journey,
)
from test_discovery import (
    test_search_finds_failed_attempts_and_filters_private_and_hidden as discovery_journey,
)
from test_notifications import (
    test_notification_retry_reference_revocation_and_filtered_summary as notification_journey,
)
from test_record_moderation import (
    test_record_hide_restore_audit_and_public_search as moderation_journey,
)
from test_records_api import record_payload
from test_records_api import (
    test_full_snapshot_edits_preserve_explicit_metadata_and_exact_targets as metadata_journey,
)
from test_records_api import (
    test_multiple_exact_targets_preserve_identity_and_moderation as multiple_targets,
)
from test_records_api import (
    test_private_public_relation_matrix as relation_matrix,
)
from test_records_api import (
    test_records_scope_history_promotion_and_paging as record_history,
)
from test_research_snapshots import (
    test_history_is_complete_batched_and_preserves_previous_content as complete_history,
)
from test_research_snapshots import (
    test_legacy_statement_release_retains_frozen_author as frozen_author,
)
from test_research_snapshots import (
    test_public_history_does_not_expose_hidden_structural_targets as hidden_structural_targets,
)
from test_research_snapshots import (
    test_snapshots_batch_children_and_work_after_session_close as materialized_snapshots,
)
from test_workspace_references import (
    test_pin_reuse_explicit_upgrade_and_private_history as reference_history,
)

from polycolab.accounts.authentication import MappingIdentityVerifier
from polycolab.agents.tools import execute_tool
from polycolab.app.application import create_app
from polycolab.db.models import SqlAgentRunEvent, SqlRunRevisionOutput
from polycolab.platform.config import Settings


@pytest.mark.parametrize(
    "journey",
    [
        multiple_targets,
        relation_matrix,
        record_history,
        reference_history,
        correction_journey,
        community_journey,
        discovery_journey,
        moderation_journey,
        notification_journey,
        complete_history,
        frozen_author,
        hidden_structural_targets,
        materialized_snapshots,
    ],
)
def test_postgresql_research_journey(
    pg_schema: tuple[Engine, Config, str],
    identity_verifier: MappingIdentityVerifier,
    journey: Callable[[TestClient], None],
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-records-web"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            journey(pg_client)
    finally:
        app.state.engine.dispose()


def test_postgresql_discovery_index_predicates(pg_schema: tuple[Engine, Config, str]) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    with engine.connect() as connection:
        # This proves index eligibility, not production cardinality or latency.
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        for table, expression, index in (
            ("object_revisions", "title || ' ' || content_md", "ix_revision_search"),
            (
                "catalogue_revisions",
                "source_identifier || ' ' || source_version || ' ' || source_locator",
                "ix_catalogue_source_search",
            ),
            ("record_revisions", "coalesce(explanation_md, '')", "ix_record_explanation_search"),
        ):
            rows = connection.execute(
                text(
                    f"EXPLAIN SELECT * FROM {table} "
                    f"WHERE to_tsvector('simple', {expression}) "
                    "@@ plainto_tsquery('simple', 'induction')"
                )
            )
            assert index in "\n".join(row[0] for row in rows)


@pytest.mark.parametrize("kind", ["ATTEMPT", "CLAIM"])
def test_postgresql_metadata_retention(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier, kind: str
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-records-web"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            metadata_journey(pg_client, kind)
    finally:
        app.state.engine.dispose()


@pytest.mark.parametrize("public", [False, True])
def test_postgresql_direct_contribution(
    pg_schema: tuple[Engine, Config, str],
    identity_verifier: MappingIdentityVerifier,
    public: bool,
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-direct-web"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            direct_journey(pg_client, public)
    finally:
        app.state.engine.dispose()


def test_postgresql_concurrent_direct_retry(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-direct-web"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            _, token, run_id, entry, project = active_run(pg_client, public=False)
            with app.state.session_factory() as db:
                cursor = db.scalar(
                    select(SqlAgentRunEvent.cursor).where(
                        SqlAgentRunEvent.run_id == run_id,
                        SqlAgentRunEvent.idempotency_key == "direct-1-requested",
                    )
                )
            assert cursor is not None
            payload = record_payload(entry["object_version_id"], project_id=project["id"])
            barrier = Barrier(2)

            def write() -> dict[str, object]:
                with app.state.session_factory() as db:
                    barrier.wait(timeout=10)
                    return execute_tool(
                        db,
                        token=token,
                        name="write_object_version",
                        arguments=payload,
                        idempotency_key="direct-1",
                        source_event_cursor=cursor,
                    )

            with ThreadPoolExecutor(max_workers=2) as pool:
                one, two = pool.submit(write), pool.submit(write)
                assert one.result(timeout=15) == two.result(timeout=15)
            with app.state.session_factory() as db:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(SqlRunRevisionOutput)
                        .where(SqlRunRevisionOutput.run_id == run_id)
                    )
                    == 1
                )
    finally:
        app.state.engine.dispose()
