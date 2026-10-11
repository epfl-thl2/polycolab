"""Real PostgreSQL evidence for the public-workspace/external-agent boundary."""

from unittest.mock import patch
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_application_configuration import (
    test_owner_visibility_changes_filter_research_and_history as verify_visibility,
)
from test_application_configuration import (
    test_private_workspace_search_preserves_access_boundaries as verify_private_search,
)
from test_public_external_agents import (
    test_external_artifact_becomes_public_only_after_attachment as verify_artifact_visibility,
)
from test_public_external_agents import (
    test_external_credential_fixed_contract_and_request_limit as verify_fixed_credential,
)
from test_public_external_agents import (
    test_external_exact_public_input_relation_scope_and_stale_edit as verify_scope_and_stale,
)
from test_public_external_agents import (
    test_external_limits_expiry_and_membership_loss_are_live as verify_live_revocation,
)
from test_public_external_agents import (
    test_public_contract_and_external_retry_revocation as verify_public_contract,
)
from test_public_external_agents import (
    test_public_workspace_moderation_and_lifecycle_filter_every_projection as verify_moderation,
)
from test_public_external_agents import (
    test_transition_and_operator_recovery_invalidate_protected_access as verify_transition_recovery,
)

from polycolab.accounts.authentication import MappingIdentityVerifier
from polycolab.app.application import create_app
from polycolab.db.models import (
    SqlObjectRevision,
    SqlProject,
    SqlResearchObject,
    SqlResearchScope,
    SqlStatementRevision,
)
from polycolab.entities.enums import ProvenanceKind, ResearchEntityClass, ResearchObjectKind
from polycolab.platform.config import Settings
from polycolab.research.contributions import human_contribution


@pytest.mark.parametrize(
    "starting_revision", ["20260914_login_rate_limits", "20260914_version_relationships"]
)
def test_unification_migration_preserves_workspace_research(
    pg_schema: tuple[Engine, Config, str],
    identity_verifier: MappingIdentityVerifier,
    starting_revision: str,
) -> None:
    from test_public_external_agents import headers

    engine, config, url = pg_schema
    command.upgrade(config, starting_revision)
    assert "beta_sample_data_installations" in inspect(engine).get_table_names()
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-migration-web"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            existing = []
            for visibility in ["PUBLIC", "PRIVATE"]:
                project = pg_client.post(
                    "/api/v1/workspaces",
                    headers=headers(),
                    json={"name": f"Preserved {visibility}", "visibility": visibility},
                ).json()
                # Seed the old schema without running a newer write API against it.
                # Current activity hooks require the not-yet-installed submission counter.
                with (
                    patch("polycolab.research.history.from_source", return_value=None),
                    Session(engine) as db,
                ):
                    owner = db.get(SqlProject, UUID(project["id"]))
                    assert owner is not None
                    scope = db.query(SqlResearchScope).filter_by(project_id=owner.id).one()
                    envelope = human_contribution(
                        db,
                        user_id=owner.created_by_user_id,
                        scope_id=scope.id,
                        operation="migration-fixture",
                    )
                    obj = SqlResearchObject(
                        ownership_scope_id=scope.id,
                        contribution_id=envelope.id,
                        kind=ResearchObjectKind.CLAIM,
                        entity_class=ResearchEntityClass.STATEMENT,
                        created_by_user_id=owner.created_by_user_id,
                        provenance_kind=ProvenanceKind.HUMAN_DIRECT,
                    )
                    db.add(obj)
                    db.flush()
                    version = SqlObjectRevision(
                        object_id=obj.id,
                        ownership_scope_id=scope.id,
                        contribution_id=envelope.id,
                        created_by_user_id=owner.created_by_user_id,
                        provenance_kind=ProvenanceKind.HUMAN_DIRECT,
                        number=1,
                        schema_version=1,
                        title="Preserved exact claim",
                        content_md="Preserved body",
                    )
                    db.add(version)
                    db.flush()
                    db.add(SqlStatementRevision(revision_id=version.id, kind="CLAIM"))
                    obj.current_revision_id = version.id
                    db.commit()
                    existing.append((project, str(obj.id), str(version.id)))
            command.upgrade(config, "head")
            assert "beta_sample_data_installations" not in inspect(engine).get_table_names()
            for project, object_id, version_id in existing:
                assert (
                    pg_client.get(f"/api/v1/workspaces/{project['id']}", headers=headers()).json()
                    == project
                )
                claim = pg_client.get(f"/api/v1/objects/{object_id}", headers=headers()).json()
                assert claim["current_object_version_id"] == version_id
                version_read = pg_client.get(f"/api/v1/versions/{version_id}", headers=headers())
                assert version_read.status_code == 200, version_read.text
                assert version_read.json()["content"]["title"] == "Preserved exact claim"
                assert version_read.json()["content"]["content_md"] == "Preserved body"
    finally:
        app.state.engine.dispose()


def test_external_agent_authority_retries_and_revocation_on_postgresql(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier
) -> None:
    engine, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-research-external-web"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            verify_transition_recovery(pg_client)
            verify_fixed_credential(pg_client)
            verify_public_contract(pg_client)
            verify_scope_and_stale(pg_client)
            verify_live_revocation(pg_client)
            verify_moderation(pg_client)
            verify_artifact_visibility(pg_client)
            verify_visibility(pg_client)
            verify_private_search(pg_client)
    finally:
        app.state.engine.dispose()

    with engine.connect() as connection:
        transaction = connection.begin()
        credential_id = connection.execute(
            text("SELECT id FROM external_agent_credentials ORDER BY id LIMIT 1")
        ).scalar_one()
        with pytest.raises(DBAPIError, match="external agent credential grant is immutable"):
            connection.execute(
                text(
                    "UPDATE external_agent_credentials "
                    "SET fixed_rights = CAST(:rights AS JSON) WHERE id = :credential_id"
                ),
                {"rights": '["WORKSPACE_WRITE"]', "credential_id": credential_id},
            )
        transaction.rollback()
