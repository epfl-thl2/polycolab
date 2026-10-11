"""Real PostgreSQL evidence for restored research semantic verification."""

from typing import cast
from uuid import UUID

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from test_research_domain import create_object, create_workspace

from polycolab.accounts.authentication import MappingIdentityVerifier
from polycolab.app.application import create_app
from polycolab.db.models import (
    SqlContributionEnvelope,
    SqlObjectRevision,
    SqlPublicationManifest,
    SqlPublicationRevision,
    SqlPublicRelease,
    SqlResearchObject,
    SqlRevisionEndorsement,
)
from polycolab.entities.enums import ContributionActorKind
from polycolab.operations.recovery_dependencies import verify_research_integrity
from polycolab.platform.config import Settings
from polycolab.platform.outbox import canonical_digest


def test_postgresql_restored_research_semantics_are_verified_read_only(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-recovery-research-web"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            project_id = create_workspace(pg_client)
            created = create_object(pg_client, project_id)
        revision_id = UUID(cast(str, created["current_object_version_id"]))
        with app.state.session_factory() as session:
            revision = session.get(SqlObjectRevision, revision_id)
            obj = session.get(SqlResearchObject, UUID(cast(str, created["id"])))
            assert revision is not None and obj is not None
            publication = SqlContributionEnvelope(
                actor_kind=ContributionActorKind.HUMAN,
                human_user_id=revision.created_by_user_id,
                ownership_scope_id=revision.ownership_scope_id,
                operation="publication.confirm",
                source_event_cursors=[],
            )
            session.add(publication)
            session.flush()
            manifest = SqlPublicationManifest(
                project_id=obj.project_id,
                ownership_scope_id=revision.ownership_scope_id,
                preview_digest="1" * 64,
                contribution_id=publication.id,
                created_by_user_id=revision.created_by_user_id,
                selection={},
                public_fields={},
            )
            session.add(manifest)
            session.flush()
            fields: dict[str, object] = {
                "object_id": str(obj.id),
                "revision_id": str(revision.id),
                "kind": "CLAIM",
                "title": "Claim",
                "content_md": "x",
                "assumptions_md": None,
                "author_display_name": "Owner",
            }
            session.add_all(
                (
                    SqlPublicationRevision(
                        manifest_id=manifest.id,
                        revision_id=revision.id,
                        position=0,
                        selected=True,
                    ),
                    SqlPublicRelease(
                        ownership_scope_id=revision.ownership_scope_id,
                        object_revision_id=revision.id,
                        contribution_id=publication.id,
                        publication_manifest_id=manifest.id,
                        projection_version=3,
                        public_fields=fields,
                        public_fields_digest=canonical_digest(fields),
                    ),
                    SqlRevisionEndorsement(
                        revision_id=revision.id,
                        active=True,
                        rationale="checked",
                        contribution_id=revision.contribution_id,
                        created_by_user_id=revision.created_by_user_id,
                    ),
                )
            )
            session.commit()
        report = verify_research_integrity(app.state.session_factory)
        assert report.status == "VERIFIED"
        assert report.checked == 6
        assert report.sections == ()
        with TestClient(app) as pg_client:
            create_object(pg_client, project_id, kind="PROOF_SKETCH")
            create_object(pg_client, project_id, kind="ATTEMPT")
        structured_report = verify_research_integrity(app.state.session_factory)
        assert structured_report.status == "VERIFIED"
        # Proof and attempt each create a target statement; all pins count too.
        assert structured_report.checked == 17
        assert structured_report.sections == ()
    finally:
        app.state.engine.dispose()
