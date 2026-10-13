"""Real PostgreSQL checks for the Research-owned artifact schema handoff."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from test_research_domain import create_object, create_project

from polycolab.accounts.authentication import MappingIdentityVerifier
from polycolab.app.application import create_app
from polycolab.db.models import SqlArtifact, SqlArtifactResearchLink, SqlObjectRevision
from polycolab.entities.enums import ArtifactResearchRole, ArtifactState
from polycolab.platform.config import Settings


def test_artifact_identity_lifecycle_and_typed_binding_constraints(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-artifact-foundation-web"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            project_id = create_project(pg_client)
            target = create_object(pg_client, project_id)
        with app.state.session_factory() as db:
            revision = db.get(SqlObjectRevision, UUID(target["current_object_version_id"]))
            assert revision is not None
            artifact = SqlArtifact(
                ownership_scope_id=revision.ownership_scope_id,
                contribution_id=revision.contribution_id,
                created_by_user_id=revision.created_by_user_id,
                sha256="1" * 64,
                byte_length=4,
                media_type="text/plain",
                storage_key=f"staging/{uuid4()}",
                state=ArtifactState.STAGING,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            db.add(artifact)
            db.commit()
            artifact_id = artifact.id
            link = SqlArtifactResearchLink(
                artifact_id=artifact.id,
                revision_id=revision.id,
                role=ArtifactResearchRole.EVIDENCE,
                contribution_id=revision.contribution_id,
                created_by_user_id=revision.created_by_user_id,
            )
            db.add(link)
            with pytest.raises(DBAPIError):
                db.commit()
            db.rollback()
            artifact = db.get(SqlArtifact, artifact_id)
            assert artifact is not None
            now = datetime.now(UTC)
            artifact.verified_at = now
            db.commit()
            artifact.state = ArtifactState.COMMITTED
            artifact.committed_at = now
            db.commit()
            db.add(
                SqlArtifactResearchLink(
                    artifact_id=artifact.id,
                    revision_id=revision.id,
                    role=ArtifactResearchRole.EVIDENCE,
                    contribution_id=revision.contribution_id,
                    created_by_user_id=revision.created_by_user_id,
                )
            )
            db.commit()
            assert (
                db.scalar(
                    select(SqlArtifactResearchLink.id).where(
                        SqlArtifactResearchLink.artifact_id == artifact.id
                    )
                )
                is not None
            )
            artifact.sha256 = "2" * 64
            with pytest.raises(DBAPIError):
                db.commit()
            db.rollback()
    finally:
        app.state.engine.dispose()
