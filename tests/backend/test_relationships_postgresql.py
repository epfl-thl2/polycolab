"""Populated upgrades and canonical exact-version relationship integrity."""

from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_m0_postgresql import seed
from test_relationship_scopes import (
    test_declaration_cannot_reference_another_projects_private_version as inaccessible_endpoint,
)
from test_relationship_scopes import (
    test_private_equivalence_between_public_versions as scoped_equivalence,
)

from polycolab.accounts.authentication import MappingIdentityVerifier
from polycolab.app.application import create_app
from polycolab.db.models import (
    SqlObjectRevision,
    SqlPublicRelease,
    SqlRecordRevision,
    SqlResearchObject,
    SqlStatementRevision,
)
from polycolab.db.models.relationships import SqlObjectVersionRelationship
from polycolab.db.stores.relationships import add_declaration, add_structural_relationship
from polycolab.db.stores.research import SqlResearchReadStore
from polycolab.entities.enums import (
    ProvenanceKind,
    RelationType,
    ResearchEntityClass,
    ResearchObjectKind,
)
from polycolab.entities.research import AttemptVersion, ProofSketchVersion, StructuralRole
from polycolab.platform.config import Settings
from polycolab.research.contributions import human_contribution


def test_scoped_equivalence_visibility_postgresql(
    pg_schema: tuple[Engine, Config, str],
    identity_verifier: MappingIdentityVerifier,
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-relationship-test-web"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            scoped_equivalence(pg_client)
            inaccessible_endpoint(pg_client)
    finally:
        app.state.engine.dispose()


@pytest.mark.parametrize(
    "starting_revision", ["20260914_login_rate_limits", "20260916_merge_hosted_main"]
)
def test_populated_upgrade_preserves_exact_relationships_and_frozen_releases(
    pg_schema: tuple[Engine, Config, str],
    starting_revision: str,
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, starting_revision)
    user_id, _, scope_id = seed(engine)
    with (
        patch("polycolab.research.history.from_source", return_value=None),
        Session(engine, expire_on_commit=False) as session,
    ):
        envelope = human_contribution(
            session, user_id=user_id, scope_id=scope_id, operation="migration-fixture"
        )

        def create(kind: ResearchObjectKind) -> SqlObjectRevision:
            statement = kind is ResearchObjectKind.CLAIM
            obj = SqlResearchObject(
                ownership_scope_id=scope_id,
                contribution_id=envelope.id,
                kind=kind,
                entity_class=ResearchEntityClass.STATEMENT
                if statement
                else ResearchEntityClass.RECORD,
                created_by_user_id=user_id,
                provenance_kind=ProvenanceKind.HUMAN_DIRECT,
            )
            session.add(obj)
            session.flush()
            version = SqlObjectRevision(
                object_id=obj.id,
                ownership_scope_id=scope_id,
                contribution_id=envelope.id,
                created_by_user_id=user_id,
                provenance_kind=ProvenanceKind.HUMAN_DIRECT,
                number=1,
                schema_version=1,
                title=kind.value,
                content_md="Original snapshot",
            )
            session.add(version)
            session.flush()
            metadata: Any = SqlStatementRevision if statement else SqlRecordRevision
            session.add(metadata(revision_id=version.id, kind=kind.value))
            obj.current_revision_id = version.id
            session.flush()
            return version

        conclusion, premise = create(ResearchObjectKind.CLAIM), create(ResearchObjectKind.CLAIM)
        proof, attempt = create(ResearchObjectKind.PROOF_SKETCH), create(ResearchObjectKind.ATTEMPT)
        result_version = SqlObjectRevision(
            object_id=conclusion.object_id,
            ownership_scope_id=scope_id,
            contribution_id=envelope.id,
            created_by_user_id=user_id,
            provenance_kind=ProvenanceKind.HUMAN_DIRECT,
            number=2,
            schema_version=1,
            title="Updated claim",
            content_md="A later complete snapshot",
            base_revision_id=conclusion.id,
        )
        session.add(result_version)
        session.flush()
        session.add(SqlStatementRevision(revision_id=result_version.id, kind="CLAIM"))
        conclusion_object = session.get(SqlResearchObject, conclusion.object_id)
        assert conclusion_object is not None
        conclusion_object.current_revision_id = result_version.id
        session.flush()
        session.execute(
            text("""
INSERT INTO proof_sketch_revisions (revision_id, conclusion_revision_id, reported_progress)
VALUES (:proof, :conclusion, 'PARTIAL')
"""),
            {"proof": proof.id, "conclusion": conclusion.id},
        )
        session.execute(
            text("""
INSERT INTO proof_sketch_premises (sketch_revision_id, premise_revision_id, position)
VALUES (:proof, :premise, 7)
"""),
            {"proof": proof.id, "premise": premise.id},
        )
        for target in (conclusion.id, premise.id):
            session.execute(
                text("""
INSERT INTO research_attachments (revision_id, statement_revision_id) VALUES (:proof, :target)
"""),
                {"proof": proof.id, "target": target},
            )
            session.execute(
                text("""
INSERT INTO record_statement_links (record_revision_id, statement_revision_id)
VALUES (:proof, :target)
"""),
                {"proof": proof.id, "target": target},
            )
        session.execute(
            text("""
INSERT INTO research_attempt_revisions
 (revision_id, target_object_id, target_revision_id, outcome, findings_md, result_revision_id)
VALUES (:attempt, :object, :target, 'PARTIAL', 'Historical findings', :result)
"""),
            {
                "attempt": attempt.id,
                "object": conclusion.object_id,
                "target": conclusion.id,
                "result": result_version.id,
            },
        )
        session.execute(
            text("""
INSERT INTO attempt_evidence_links (attempt_revision_id, evidence_revision_id, role, position)
VALUES (:attempt, :proof, 'SUPPORTS', 0)
"""),
            {"attempt": attempt.id, "proof": proof.id},
        )
        relation_ids = (uuid4(), uuid4())
        for relation_id, kind in zip(relation_ids, ("USES", "EQUIVALENT_TO"), strict=True):
            session.execute(
                text("""
INSERT INTO relation_assertions (id, ownership_scope_id, source_revision_id, target_revision_id,
 relation_type, rationale, contribution_id, created_by_user_id, provenance_kind, created_at)
VALUES (:id, :scope, :source, :target, :kind, 'Original declaration', :envelope, :user,
 'HUMAN_DIRECT', CURRENT_TIMESTAMP)
"""),
                {
                    "id": relation_id,
                    "scope": scope_id,
                    "source": conclusion.id,
                    "target": premise.id,
                    "kind": kind,
                    "envelope": envelope.id,
                    "user": user_id,
                },
            )
        frozen = {"title": "Original frozen title", "revision_id": str(conclusion.id)}
        release = SqlPublicRelease(
            ownership_scope_id=scope_id,
            object_revision_id=conclusion.id,
            contribution_id=envelope.id,
            projection_version=1,
            public_fields=frozen,
            public_fields_digest="a" * 64,
        )
        session.add(release)
        session.commit()
        release_id = release.id
        version_ids = [proof.id, attempt.id]

    command.upgrade(config, "head")
    with Session(engine) as session:
        rows = list(session.scalars(select(SqlObjectVersionRelationship)))
        assert len(rows) == 9  # seven structural rows, two independent declarations
        assert len([row for row in rows if row.relationship_type == "ATTACHMENT"]) == 2
        for relation_id in relation_ids:
            row = session.get(SqlObjectVersionRelationship, relation_id)
            assert row is not None and row.description == "Original declaration"
            assert row.contribution_id == envelope.id
        equivalent = session.get(SqlObjectVersionRelationship, relation_ids[1])
        assert equivalent is not None and equivalent.source_object_version_id is None
        assert [equivalent.first_object_version_id, equivalent.second_object_version_id] == sorted(
            (conclusion.id, premise.id)
        )
        saved_release = session.get(SqlPublicRelease, release_id)
        assert saved_release is not None and saved_release.public_fields == frozen
        assert saved_release.public_fields_digest == "a" * 64
        versions = SqlResearchReadStore(session).versions(version_ids)
        proof_snapshot = versions[proof.id]
        attempt_snapshot = versions[attempt.id]
        assert isinstance(proof_snapshot, ProofSketchVersion)
        assert proof_snapshot.premise_object_version_ids == (premise.id,)
        assert (
            next(
                r.position
                for r in proof_snapshot.structural_relationships
                if r.relationship_type is StructuralRole.PREMISE
            )
            == 7
        )
        assert isinstance(attempt_snapshot, AttemptVersion)
        assert attempt_snapshot.evidence[0].object_version_id == proof.id
        assert attempt_snapshot.result_object_version_id == result_version.id
        assert attempt_snapshot.content.findings_md == "Historical findings"
    tables = inspect(engine).get_table_names()
    assert "object_version_relationships" in tables
    assert not {
        "relation_assertions",
        "research_attachments",
        "record_statement_links",
        "proof_sketch_premises",
        "attempt_evidence_links",
    }.intersection(tables)

    with pytest.raises(DBAPIError, match="created with its version"):
        with Session(engine) as session, session.begin():
            add_structural_relationship(
                session,
                source_object_version_id=proof.id,
                target_object_version_id=conclusion.id,
                relationship_type=StructuralRole.ATTACHMENT,
            )
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM object_version_relationships WHERE id=:id"),
                {"id": relation_ids[0]},
            )
    with Session(engine) as session, session.begin():
        new_envelope = human_contribution(
            session, user_id=user_id, scope_id=scope_id, operation="independent-declaration"
        )
        added = add_declaration(
            session,
            source_revision_id=conclusion.id,
            target_revision_id=premise.id,
            relation_type=RelationType.EQUIVALENT_TO,
            ownership_scope_id=scope_id,
            contribution_id=new_envelope.id,
            created_by_user_id=user_id,
            provenance_kind=ProvenanceKind.HUMAN_DIRECT,
            rationale="A later declaration",
        )
        assert added.id not in relation_ids
