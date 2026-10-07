"""Unify exact-version relationships without rewriting published history."""

from alembic import op

revision = "20260914_version_relationships"
down_revision = "20260914_login_rate_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE object_version_relationships (
	id UUID NOT NULL,

	relationship_type VARCHAR(32) NOT NULL,

	binding VARCHAR(16) NOT NULL,

	direction VARCHAR(16) NOT NULL,

	source_object_version_id UUID,

	target_object_version_id UUID,

	first_object_version_id UUID,

	second_object_version_id UUID,

	position INTEGER,

	evidence_role VARCHAR(16),

	ownership_scope_id UUID NOT NULL,

	contribution_id UUID NOT NULL,

	created_by_user_id UUID NOT NULL,

	provenance_kind VARCHAR(32) NOT NULL,

	description TEXT,

	created_at TIMESTAMP WITH TIME ZONE NOT NULL,

	PRIMARY KEY (id),

CONSTRAINT ck_relationship_endpoints CHECK ((direction = 'UNIDIRECTIONAL' AND
source_object_version_id IS NOT NULL AND target_object_version_id IS NOT NULL AND
first_object_version_id IS NULL AND second_object_version_id IS NULL) OR (direction =
'BIDIRECTIONAL' AND source_object_version_id IS NULL AND target_object_version_id IS NULL AND
first_object_version_id IS NOT NULL AND second_object_version_id IS NOT NULL AND
first_object_version_id <= second_object_version_id)),

CONSTRAINT ck_relationship_type_binding CHECK ((binding = 'STRUCTURAL' AND direction =
'UNIDIRECTIONAL' AND relationship_type IN
('ATTACHMENT','CONCLUSION','PREMISE','TARGET','EVIDENCE','RESULT')) OR (binding = 'DECLARATION'
AND ((direction = 'BIDIRECTIONAL' AND relationship_type = 'EQUIVALENT_TO') OR (direction =
'UNIDIRECTIONAL' AND relationship_type IN
('DEPENDS_ON','PROVES','ATTEMPTS','REFUTES','USES','IMPLIES'))))),

CONSTRAINT ck_relationship_position CHECK ((relationship_type IN ('PREMISE','EVIDENCE') AND
position IS NOT NULL AND position >= 0) OR (relationship_type NOT IN ('PREMISE','EVIDENCE') AND
position IS NULL)),

CONSTRAINT ck_relationship_evidence_role CHECK ((relationship_type = 'EVIDENCE' AND evidence_role
IS NOT NULL AND evidence_role IN ('INPUT','SUPPORTS','CONTRADICTS','OUTPUT')) OR
(relationship_type <> 'EVIDENCE' AND evidence_role IS NULL)),

CONSTRAINT ck_relationship_provenance CHECK (provenance_kind IN
('HUMAN_DIRECT','AGENT_PROPOSAL','AGENT_DIRECT')),

	FOREIGN KEY(source_object_version_id) REFERENCES object_revisions (id),

	FOREIGN KEY(target_object_version_id) REFERENCES object_revisions (id),

	FOREIGN KEY(first_object_version_id) REFERENCES object_revisions (id),

	FOREIGN KEY(second_object_version_id) REFERENCES object_revisions (id),

	FOREIGN KEY(ownership_scope_id) REFERENCES research_scopes (id),

	FOREIGN KEY(contribution_id) REFERENCES contribution_envelopes (id),

	FOREIGN KEY(created_by_user_id) REFERENCES users (id)
);
CREATE INDEX ix_object_version_relationships_contribution_id ON object_version_relationships
(contribution_id);
CREATE INDEX ix_object_version_relationships_created_by_user_id ON object_version_relationships
(created_by_user_id);
CREATE INDEX ix_object_version_relationships_first_object_version_id ON
object_version_relationships (first_object_version_id);
CREATE INDEX ix_object_version_relationships_ownership_scope_id ON object_version_relationships
(ownership_scope_id);
CREATE INDEX ix_object_version_relationships_second_object_version_id ON
object_version_relationships (second_object_version_id);
CREATE INDEX ix_object_version_relationships_source_object_version_id ON
object_version_relationships (source_object_version_id);
CREATE INDEX ix_object_version_relationships_target_object_version_id ON
object_version_relationships (target_object_version_id);
CREATE UNIQUE INDEX uq_structural_position ON object_version_relationships
(source_object_version_id,
relationship_type,
position) WHERE position IS NOT NULL;
CREATE UNIQUE INDEX uq_structural_relationship ON object_version_relationships
(source_object_version_id,
relationship_type,
target_object_version_id) WHERE binding = 'STRUCTURAL';
CREATE UNIQUE INDEX uq_structural_single_target ON object_version_relationships
(source_object_version_id,
relationship_type) WHERE relationship_type IN ('CONCLUSION','TARGET','RESULT')
""")
    # Declarations retain their IDs, scope and attribution. Endpoint order is
    # canonical only for symmetric relationships; it never conveys endorsement.
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
 CASE WHEN relation_type = 'EQUIVALENT_TO' THEN LEAST(source_revision_id, target_revision_id) END,
CASE WHEN relation_type = 'EQUIVALENT_TO' THEN GREATEST(source_revision_id, target_revision_id)
END,
 ownership_scope_id, contribution_id, created_by_user_id, provenance_kind, rationale, created_at
FROM relation_assertions
""")
    # UNION removes only duplicate representations of the same attachment.
    # It does not combine different roles or separately authored declarations.
    op.execute("""
CREATE TEMP TABLE relationship_backfill ON COMMIT DROP AS
SELECT revision_id AS source_id, statement_revision_id AS target_id,
 'ATTACHMENT'::varchar(32) AS role, NULL::integer AS position,
 NULL::varchar(16) AS evidence_role FROM research_attachments
UNION
SELECT record_revision_id, statement_revision_id, 'ATTACHMENT', NULL, NULL
 FROM record_statement_links
UNION ALL
SELECT revision_id, conclusion_revision_id, 'CONCLUSION', NULL, NULL
 FROM proof_sketch_revisions
UNION ALL
SELECT sketch_revision_id, premise_revision_id, 'PREMISE', position, NULL
 FROM proof_sketch_premises
UNION ALL
SELECT revision_id, target_revision_id, 'TARGET', NULL, NULL
 FROM research_attempt_revisions
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
SELECT gen_random_uuid(), b.role, 'STRUCTURAL', 'UNIDIRECTIONAL', b.source_id,
 b.target_id, b.position, b.evidence_role, v.ownership_scope_id, v.contribution_id,
 v.created_by_user_id, v.provenance_kind, v.created_at
FROM relationship_backfill b JOIN object_revisions v ON v.id = b.source_id
""")
    op.execute("""
DO $$ BEGIN
IF (SELECT count(*) FROM relation_assertions) <>
 (SELECT count(*) FROM object_version_relationships WHERE binding = 'DECLARATION')
 OR (SELECT count(*) FROM relationship_backfill) <>
 (SELECT count(*) FROM object_version_relationships WHERE binding = 'STRUCTURAL')
THEN RAISE EXCEPTION 'relationship backfill count mismatch'; END IF;
END $$
""")
    for table in ("contribution_entity_links", "publication_relations"):
        name = f"{table}_relation_id_fkey"
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, "object_version_relationships", ["relation_id"], ["id"])

    for table in (
        "record_statement_links",
        "research_attachments",
        "proof_sketch_premises",
        "attempt_evidence_links",
        "relation_assertions",
    ):
        op.drop_table(table)
    op.execute("DROP TRIGGER research_attempt_target_valid ON research_attempt_revisions")
    op.execute("DROP FUNCTION validate_research_attempt()")
    # Verification keeps its immutable request columns, but attempt targets now
    # come exclusively from the canonical exact-version relationship store.
    op.execute("""
CREATE OR REPLACE FUNCTION validate_verification_job() RETURNS trigger AS $$
DECLARE target_scope uuid; attempt_target uuid;
BEGIN
 SELECT ownership_scope_id INTO target_scope FROM object_revisions
 WHERE id = NEW.work_target_revision_id;
 IF target_scope IS DISTINCT FROM NEW.ownership_scope_id THEN
  RAISE EXCEPTION 'verification target must belong to the owning scope'; END IF;
 IF NEW.research_attempt_revision_id IS NOT NULL THEN
  SELECT r.target_object_version_id INTO attempt_target
  FROM object_version_relationships r
  JOIN research_attempt_revisions a ON a.revision_id = r.source_object_version_id
  WHERE a.revision_id = NEW.research_attempt_revision_id
   AND r.binding = 'STRUCTURAL' AND r.relationship_type = 'TARGET';
  IF attempt_target IS DISTINCT FROM NEW.work_target_revision_id THEN
   RAISE EXCEPTION 'research attempt must target the verification work revision'; END IF;
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql
""")
    op.drop_column("proof_sketch_revisions", "conclusion_revision_id")
    for column in ("target_revision_id", "target_object_id", "result_revision_id"):
        op.drop_column("research_attempt_revisions", column)

    # Existing output-scope validation consumes a read-only compatibility view.
    # The canonical table remains the only relationship storage.
    op.execute("""
CREATE VIEW relation_assertions AS
SELECT id, ownership_scope_id, contribution_id, created_by_user_id, provenance_kind, created_at,
 COALESCE(source_object_version_id, first_object_version_id) AS source_revision_id,
 COALESCE(target_object_version_id, second_object_version_id) AS target_revision_id,
 relationship_type AS relation_type, COALESCE(description, '') AS rationale
FROM object_version_relationships WHERE binding = 'DECLARATION'
""")
    op.execute("""
CREATE FUNCTION protect_object_version_relationship() RETURNS trigger AS $$
DECLARE source object_revisions; insertion_xid bigint;
BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'relationship history is immutable'; END IF;
IF NEW.direction = 'UNIDIRECTIONAL' THEN
 SELECT * INTO source FROM object_revisions WHERE id = NEW.source_object_version_id;
 IF source.ownership_scope_id IS DISTINCT FROM NEW.ownership_scope_id THEN
  RAISE EXCEPTION 'relationship source scope mismatch';
 END IF;
END IF;
IF NEW.binding = 'STRUCTURAL' THEN
 SELECT xmin::text::bigint INTO insertion_xid FROM object_revisions WHERE id = source.id;
 IF insertion_xid IS DISTINCT FROM (txid_current() % 4294967296) THEN
  RAISE EXCEPTION 'research structure must be created with its version';
 END IF;
 IF NEW.contribution_id IS DISTINCT FROM source.contribution_id
  OR NEW.created_by_user_id IS DISTINCT FROM source.created_by_user_id
  OR NEW.provenance_kind IS DISTINCT FROM source.provenance_kind
  OR NEW.created_at IS DISTINCT FROM source.created_at THEN
  RAISE EXCEPTION 'structural authorship must match its version';
 END IF;
 IF NEW.relationship_type IN ('ATTACHMENT','CONCLUSION','PREMISE') AND NOT EXISTS (
  SELECT 1 FROM statement_revisions WHERE revision_id = NEW.target_object_version_id
 ) THEN RAISE EXCEPTION 'structural target must be a statement'; END IF;
END IF;
RETURN NEW; END $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER object_version_relationships_immutable
BEFORE INSERT OR UPDATE OR DELETE ON object_version_relationships
FOR EACH ROW EXECUTE FUNCTION protect_object_version_relationship()
""")
    op.execute("""
CREATE TRIGGER object_version_relationships_contribution
BEFORE INSERT ON object_version_relationships
FOR EACH ROW EXECUTE FUNCTION validate_research_contribution()
""")
    op.execute("""
CREATE FUNCTION validate_object_version_relationships() RETURNS trigger AS $$
DECLARE version_id uuid; record_kind varchar(32); conclusion_id uuid;
 target object_revisions; result object_revisions;
BEGIN
IF TG_TABLE_NAME = 'object_version_relationships' THEN
 IF NEW.binding <> 'STRUCTURAL' THEN RETURN NULL; END IF;
 version_id = NEW.source_object_version_id;
ELSE version_id = NEW.revision_id; END IF;
SELECT kind INTO record_kind FROM record_revisions WHERE revision_id = version_id;
IF EXISTS (SELECT 1 FROM object_version_relationships
 WHERE source_object_version_id = version_id AND relationship_type IN ('CONCLUSION','PREMISE'))
 AND NOT EXISTS (SELECT 1 FROM proof_sketch_revisions WHERE revision_id = version_id)
THEN RAISE EXCEPTION 'proof relationships require proof structure'; END IF;
IF EXISTS (SELECT 1 FROM proof_sketch_revisions WHERE revision_id = version_id) THEN
 SELECT target_object_version_id INTO conclusion_id FROM object_version_relationships
 WHERE source_object_version_id = version_id AND relationship_type = 'CONCLUSION';
 IF conclusion_id IS NULL THEN RAISE EXCEPTION 'proof requires a conclusion'; END IF;
 IF EXISTS (SELECT 1 FROM object_version_relationships
  WHERE source_object_version_id = version_id AND relationship_type = 'PREMISE'
  AND target_object_version_id = conclusion_id)
 THEN RAISE EXCEPTION 'a conclusion cannot be its own premise'; END IF;
 IF EXISTS (
  SELECT 1 FROM object_version_relationships d WHERE d.source_object_version_id = version_id
  AND d.relationship_type IN ('CONCLUSION','PREMISE') AND NOT EXISTS (
   SELECT 1 FROM object_version_relationships a
   WHERE a.source_object_version_id = version_id AND a.relationship_type = 'ATTACHMENT'
    AND a.target_object_version_id = d.target_object_version_id))
 THEN RAISE EXCEPTION 'proof dependencies must be attachments'; END IF;
END IF;
IF EXISTS (SELECT 1 FROM object_version_relationships
WHERE source_object_version_id = version_id AND relationship_type IN
('TARGET','RESULT','EVIDENCE'))
 AND NOT EXISTS (SELECT 1 FROM research_attempt_revisions WHERE revision_id = version_id)
THEN RAISE EXCEPTION 'attempt relationships require attempt structure'; END IF;
IF EXISTS (SELECT 1 FROM research_attempt_revisions WHERE revision_id = version_id) THEN
 SELECT v.* INTO target FROM object_revisions v JOIN object_version_relationships r
 ON r.target_object_version_id = v.id
 WHERE r.source_object_version_id = version_id AND r.relationship_type = 'TARGET';
 IF target.id IS NULL THEN RAISE EXCEPTION 'attempt requires a target'; END IF;
 IF EXISTS (SELECT 1 FROM research_objects WHERE id = target.object_id AND kind = 'ATTEMPT')
 THEN RAISE EXCEPTION 'attempts cannot target attempts'; END IF;
 SELECT v.* INTO result FROM object_revisions v JOIN object_version_relationships r
 ON r.target_object_version_id = v.id
 WHERE r.source_object_version_id = version_id AND r.relationship_type = 'RESULT';
 IF result.id IS NOT NULL AND
 (result.object_id <> target.object_id OR result.number <= target.number)
 THEN RAISE EXCEPTION 'attempt result must be a newer version of its target object'; END IF;
END IF;
RETURN NULL; END $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE CONSTRAINT TRIGGER canonical_relationships_complete
AFTER INSERT ON object_version_relationships DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION validate_object_version_relationships()
""")
    for table in ("proof_sketch_revisions", "research_attempt_revisions"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {table}_relationships_complete "
            f"AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED "
            "FOR EACH ROW EXECUTE FUNCTION validate_object_version_relationships()"
        )


def downgrade() -> None:
    raise RuntimeError("Relationship history cannot be losslessly downgraded; restore a backup.")
