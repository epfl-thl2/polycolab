"""Real migration evidence: old secrets stay revoked and new grants stay immutable."""

from typing import Any, cast
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from test_m0_postgresql import pg_schema as pg_schema
from test_m0_postgresql import seed
from test_shared_agent_api import (
    test_account_key_reads_future_memberships_and_writes_without_run as verify_account_scope,
)
from test_shared_agent_api import (
    test_replay_conflict_and_revocation_authorize_before_receipt as verify_replay,
)

from polycolab.app.application import create_app
from polycolab.platform.config import Settings


def test_upgrade_revokes_legacy_and_new_account_runs_keep_destination(
    pg_schema: tuple[Engine, Config, str], client: TestClient
) -> None:
    engine, config, url = pg_schema
    command.upgrade(config, "20260910_credential_rights")
    user_id, project_id, _ = seed(engine)
    credential_id, run_id = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO external_agent_credentials
            (id,project_id,sponsor_user_id,name,token_digest,fixed_rights,expires_at,max_requests,max_mutations,request_count,mutation_count,created_at)
            VALUES (:id,:project,:user,'Legacy',:digest,'[]',
                CURRENT_TIMESTAMP + INTERVAL '1 day',100,20,0,0,CURRENT_TIMESTAMP)"""),
            {"id": credential_id, "project": project_id, "user": user_id, "digest": "a" * 64},
        )
        connection.execute(
            text("""INSERT INTO external_research_runs
            (id,credential_id,project_id,sponsor_user_id,client_request_id,title,input_revision_ids,status,created_at)
            VALUES (:id,:credential,:project,:user,:request,
                'Historical','[]','OPEN',CURRENT_TIMESTAMP)"""),
            {
                "id": run_id,
                "credential": credential_id,
                "project": project_id,
                "user": user_id,
                "request": uuid4(),
            },
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        key = connection.execute(
            text(
                "SELECT scope_kind, revoked_at, project_id, agent_id, allow_library_contributions "
                "FROM external_agent_credentials "
                "WHERE id=:id"
            ),
            {"id": credential_id},
        ).one()
        assert key.scope_kind == "WORKSPACE" and key.revoked_at and key.project_id == project_id
        assert key.agent_id == credential_id
        assert key.allow_library_contributions is False
        old_run = connection.execute(
            text("SELECT status, closed_at FROM external_research_runs WHERE id=:id"),
            {"id": run_id},
        ).one()
        assert old_run.status == "REVOKED" and old_run.closed_at
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-test-web"),
        cast(Any, client.app).state.identity_verifier,
    )
    try:
        with TestClient(app) as pg:
            verify_account_scope(pg)
            # Independent scenario sees existing workspaces; replay has no count assumptions.
            verify_replay(pg)
    finally:
        app.state.engine.dispose()
    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(DBAPIError, match="grant is immutable"):
            connection.execute(
                text(
                    "UPDATE external_agent_credentials SET scope_kind='ACCOUNT', "
                    "project_id=NULL WHERE id=:id"
                ),
                {"id": credential_id},
            )
        transaction.rollback()
