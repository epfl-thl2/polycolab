"""Preserve local research while canonicalizing exact-version relationships."""

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "local_20260916_versions"
down_revision = "local_20260916_hosted"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = json.loads(Path(__file__).with_name("20260916_versions_schema.json").read_text())
    for statement in statements:
        op.execute(statement)
    op.execute("""
INSERT INTO object_version_relationships (
 id, relationship_type, binding, direction, source_object_version_id,
 target_object_version_id, first_object_version_id, second_object_version_id,
 ownership_scope_id, contribution_id, created_by_user_id, provenance_kind,
 description, created_at)
SELECT id, relation_type, 'DECLARATION',
 CASE WHEN relation_type = 'EQUIVALENT_TO' THEN 'BIDIRECTIONAL' ELSE 'UNIDIRECTIONAL' END,
 CASE WHEN relation_type <> 'EQUIVALENT_TO' THEN source_revision_id END,
 CASE WHEN relation_type <> 'EQUIVALENT_TO' THEN target_revision_id END,
 CASE WHEN relation_type = 'EQUIVALENT_TO' THEN min(source_revision_id, target_revision_id) END,
 CASE WHEN relation_type = 'EQUIVALENT_TO' THEN max(source_revision_id, target_revision_id) END,
 ownership_scope_id, contribution_id, created_by_user_id, provenance_kind, rationale, created_at
FROM relation_assertions
""")
    op.execute("""
CREATE TEMP TABLE relationship_backfill AS
SELECT revision_id AS source_id, statement_revision_id AS target_id,
 'ATTACHMENT' AS role, NULL AS position, NULL AS evidence_role FROM research_attachments
UNION
SELECT record_revision_id, statement_revision_id, 'ATTACHMENT', NULL, NULL
 FROM record_statement_links
UNION ALL
SELECT revision_id, conclusion_revision_id, 'CONCLUSION', NULL, NULL FROM proof_sketch_revisions
UNION ALL
SELECT sketch_revision_id, premise_revision_id, 'PREMISE', position, NULL FROM proof_sketch_premises
UNION ALL
SELECT revision_id, target_revision_id, 'TARGET', NULL, NULL FROM research_attempt_revisions
UNION ALL
SELECT revision_id, result_revision_id, 'RESULT', NULL, NULL
 FROM research_attempt_revisions WHERE result_revision_id IS NOT NULL
UNION ALL
SELECT attempt_revision_id, evidence_revision_id, 'EVIDENCE', position, role
 FROM attempt_evidence_links
""")
    op.execute("""
INSERT INTO object_version_relationships (
 id, relationship_type, binding, direction, source_object_version_id,
 target_object_version_id, position, evidence_role, ownership_scope_id,
 contribution_id, created_by_user_id, provenance_kind, created_at)
SELECT lower(hex(randomblob(16))), b.role, 'STRUCTURAL', 'UNIDIRECTIONAL', b.source_id,
 b.target_id, b.position, b.evidence_role, v.ownership_scope_id, v.contribution_id,
 v.created_by_user_id, v.provenance_kind, v.created_at
FROM relationship_backfill b JOIN object_revisions v ON v.id = b.source_id
""")
    connection = op.get_bind()
    for source, binding in (
        ("relation_assertions", "DECLARATION"),
        ("relationship_backfill", "STRUCTURAL"),
    ):
        before = connection.scalar(sa.text(f"SELECT count(*) FROM {source}"))
        after = connection.scalar(
            sa.text("SELECT count(*) FROM object_version_relationships WHERE binding = :binding"),
            {"binding": binding},
        )
        if before != after:
            raise RuntimeError("Relationship backfill count mismatch")
    op.execute("DROP TABLE relationship_backfill")
    convention = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    for table in ("contribution_entity_links", "publication_relations"):
        with op.batch_alter_table(table, naming_convention=convention) as batch:
            batch.drop_constraint(f"fk_{table}_relation_id_relation_assertions", type_="foreignkey")
            batch.create_foreign_key(
                f"fk_{table}_relationship", "object_version_relationships", ["relation_id"], ["id"]
            )
    for table in (
        "record_statement_links",
        "research_attachments",
        "proof_sketch_premises",
        "attempt_evidence_links",
        "relation_assertions",
    ):
        op.drop_table(table)
    with op.batch_alter_table("proof_sketch_revisions") as batch:
        batch.drop_index("ix_proof_sketch_revisions_conclusion_revision_id")
        batch.drop_column("conclusion_revision_id")
    with op.batch_alter_table("research_attempt_revisions") as batch:
        batch.drop_constraint("fk_research_attempt_target_revision_object", type_="foreignkey")
        batch.drop_constraint("fk_research_attempt_result_revision_object", type_="foreignkey")
        for column in ("target_revision_id", "target_object_id", "result_revision_id"):
            batch.drop_index(f"ix_research_attempt_revisions_{column}")
            batch.drop_column(column)


def downgrade() -> None:
    raise RuntimeError("Local downgrades are unsupported; restore the pre-upgrade backup.")
