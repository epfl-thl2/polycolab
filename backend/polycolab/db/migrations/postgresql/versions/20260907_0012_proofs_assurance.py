"""Research structure and independent assurance histories."""

from alembic import op

revision = "20260907_proofs_assurance"
down_revision = "20260907_research_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE research_objects DROP CONSTRAINT ck_research_objects_kind")
    op.execute("""
ALTER TABLE research_objects ADD CONSTRAINT ck_research_objects_kind CHECK
 (kind IN ('PROBLEM','DEFINITION','CLAIM','PROOF','PROOF_SKETCH','ATTEMPT',
           'COUNTEREXAMPLE','NOTE','IDEA','DISCUSSION'))
""")
    op.execute("ALTER TABLE record_revisions DROP CONSTRAINT ck_record_kind")
    op.execute("""
ALTER TABLE record_revisions ADD CONSTRAINT ck_record_kind CHECK
 (kind IN ('NOTE','IDEA','ATTEMPT','PROOF','PROOF_SKETCH','DISCUSSION',
           'COUNTEREXAMPLE','FORMALIZATION','COMPUTATION'))
""")
    _create_sketch_and_attempt_tables()
    _create_associated_research_tables()
    _create_assurance_tables()
    _create_integrity_triggers()


def _create_sketch_and_attempt_tables() -> None:
    op.execute("""
CREATE TABLE proof_sketch_revisions (
 revision_id UUID PRIMARY KEY REFERENCES record_revisions(revision_id),
 conclusion_revision_id UUID NOT NULL REFERENCES statement_revisions(revision_id),
 reported_progress VARCHAR(16) NOT NULL,
 CONSTRAINT ck_proof_sketch_progress CHECK
  (reported_progress IN ('POTENTIAL','PARTIAL','COMPLETE','STALLED','FAILED'))
)
""")
    op.execute(
        "CREATE INDEX ix_proof_sketch_revisions_conclusion_revision_id "
        "ON proof_sketch_revisions(conclusion_revision_id)"
    )
    op.execute("""
CREATE TABLE proof_sketch_premises (
 sketch_revision_id UUID NOT NULL REFERENCES proof_sketch_revisions(revision_id),
 premise_revision_id UUID NOT NULL REFERENCES statement_revisions(revision_id),
 position INTEGER NOT NULL,
 PRIMARY KEY (sketch_revision_id, premise_revision_id),
 CONSTRAINT uq_proof_sketch_premise_position UNIQUE (sketch_revision_id, position),
 CONSTRAINT ck_proof_sketch_premise_position CHECK (position >= 0)
)
""")
    op.execute(
        "CREATE INDEX ix_proof_sketch_premises_premise_revision_id "
        "ON proof_sketch_premises(premise_revision_id)"
    )
    op.execute("""
CREATE TABLE research_attempt_revisions (
 revision_id UUID PRIMARY KEY REFERENCES record_revisions(revision_id),
 target_object_id UUID NOT NULL REFERENCES research_objects(id),
 target_revision_id UUID NOT NULL,
 outcome VARCHAR(16) NOT NULL,
 findings_md TEXT NOT NULL,
 result_revision_id UUID,
 CONSTRAINT fk_research_attempt_target_revision_object FOREIGN KEY
  (target_revision_id, target_object_id) REFERENCES object_revisions(id, object_id),
 CONSTRAINT fk_research_attempt_result_revision_object FOREIGN KEY
  (result_revision_id, target_object_id) REFERENCES object_revisions(id, object_id),
 CONSTRAINT ck_research_attempt_outcome CHECK
  (outcome IN ('POTENTIAL','PARTIAL','COMPLETE','STALLED','FAILED'))
)
""")
    for column in ("target_object_id", "target_revision_id", "result_revision_id"):
        op.execute(
            f"CREATE INDEX ix_research_attempt_revisions_{column} "
            f"ON research_attempt_revisions({column})"
        )
    op.execute("""
CREATE TABLE attempt_evidence_links (
 attempt_revision_id UUID NOT NULL REFERENCES research_attempt_revisions(revision_id),
 evidence_revision_id UUID NOT NULL REFERENCES object_revisions(id),
 role VARCHAR(16) NOT NULL,
 position INTEGER NOT NULL,
 PRIMARY KEY (attempt_revision_id, evidence_revision_id),
 CONSTRAINT uq_attempt_evidence_position UNIQUE (attempt_revision_id, position),
 CONSTRAINT ck_attempt_evidence_position CHECK (position >= 0),
 CONSTRAINT ck_attempt_evidence_role CHECK
  (role IN ('INPUT','SUPPORTS','CONTRADICTS','OUTPUT'))
)
""")
    op.execute(
        "CREATE INDEX ix_attempt_evidence_links_evidence_revision_id "
        "ON attempt_evidence_links(evidence_revision_id)"
    )


def _create_associated_research_tables() -> None:
    op.execute("""
CREATE TABLE human_notes (
 object_id UUID PRIMARY KEY,
 ownership_scope_id UUID NOT NULL REFERENCES research_scopes(id),
 owner_user_id UUID NOT NULL REFERENCES users(id),
 current_revision_id UUID,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 CONSTRAINT fk_human_note_object_scope FOREIGN KEY (object_id, ownership_scope_id)
  REFERENCES research_objects(id, ownership_scope_id)
)
""")
    op.execute("CREATE INDEX ix_human_notes_ownership_scope_id ON human_notes(ownership_scope_id)")
    op.execute("CREATE INDEX ix_human_notes_owner_user_id ON human_notes(owner_user_id)")
    op.execute(
        "CREATE INDEX ix_human_notes_current_revision_id ON human_notes(current_revision_id)"
    )
    op.execute("""
CREATE TABLE human_note_revisions (
 id UUID PRIMARY KEY,
 object_id UUID NOT NULL REFERENCES human_notes(object_id),
 number INTEGER NOT NULL,
 base_revision_id UUID,
 body_md TEXT NOT NULL,
 contribution_id UUID NOT NULL REFERENCES contribution_envelopes(id),
 created_by_user_id UUID NOT NULL REFERENCES users(id),
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 CONSTRAINT uq_human_note_revision_number UNIQUE (object_id, number),
 CONSTRAINT uq_human_note_revision_id_object UNIQUE (id, object_id),
 CONSTRAINT fk_human_note_revision_base FOREIGN KEY (base_revision_id, object_id)
  REFERENCES human_note_revisions(id, object_id),
 CONSTRAINT ck_human_note_revision_number CHECK (number > 0)
)
""")
    op.execute("""
ALTER TABLE human_notes ADD CONSTRAINT fk_human_note_current_revision
 FOREIGN KEY (current_revision_id, object_id) REFERENCES human_note_revisions(id, object_id)
 DEFERRABLE INITIALLY DEFERRED
""")
    for column in ("object_id", "contribution_id", "created_by_user_id"):
        op.execute(
            f"CREATE INDEX ix_human_note_revisions_{column} ON human_note_revisions({column})"
        )
    op.execute("""
CREATE TABLE research_summaries (
 object_id UUID PRIMARY KEY,
 ownership_scope_id UUID NOT NULL REFERENCES research_scopes(id),
 owner_user_id UUID NOT NULL REFERENCES users(id),
 current_revision_id UUID,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 CONSTRAINT fk_research_summary_object_scope FOREIGN KEY (object_id, ownership_scope_id)
  REFERENCES research_objects(id, ownership_scope_id)
)
""")
    op.execute(
        "CREATE INDEX ix_research_summaries_ownership_scope_id "
        "ON research_summaries(ownership_scope_id)"
    )
    op.execute(
        "CREATE INDEX ix_research_summaries_owner_user_id ON research_summaries(owner_user_id)"
    )
    op.execute(
        "CREATE INDEX ix_research_summaries_current_revision_id "
        "ON research_summaries(current_revision_id)"
    )
    op.execute("""
CREATE TABLE research_summary_revisions (
 id UUID PRIMARY KEY,
 object_id UUID NOT NULL REFERENCES research_summaries(object_id),
 number INTEGER NOT NULL,
 base_revision_id UUID,
 body_md TEXT NOT NULL,
 contribution_id UUID NOT NULL REFERENCES contribution_envelopes(id),
 created_by_user_id UUID NOT NULL REFERENCES users(id),
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 CONSTRAINT uq_research_summary_revision_number UNIQUE (object_id, number),
 CONSTRAINT uq_research_summary_revision_id_object UNIQUE (id, object_id),
 CONSTRAINT fk_research_summary_revision_base FOREIGN KEY (base_revision_id, object_id)
  REFERENCES research_summary_revisions(id, object_id),
 CONSTRAINT ck_research_summary_revision_number CHECK (number > 0)
)
""")
    op.execute("""
ALTER TABLE research_summaries ADD CONSTRAINT fk_research_summary_current_revision
 FOREIGN KEY (current_revision_id, object_id)
 REFERENCES research_summary_revisions(id, object_id) DEFERRABLE INITIALLY DEFERRED
""")
    for column in ("object_id", "contribution_id", "created_by_user_id"):
        op.execute(
            "CREATE INDEX ix_research_summary_revisions_"
            f"{column} ON research_summary_revisions({column})"
        )
    op.execute("""
CREATE TABLE summary_source_revisions (
 summary_revision_id UUID NOT NULL REFERENCES research_summary_revisions(id),
 source_revision_id UUID NOT NULL REFERENCES object_revisions(id),
 position INTEGER NOT NULL,
 PRIMARY KEY (summary_revision_id, source_revision_id),
 CONSTRAINT uq_summary_source_position UNIQUE (summary_revision_id, position),
 CONSTRAINT ck_summary_source_position CHECK (position >= 0)
)
""")
    op.execute(
        "CREATE INDEX ix_summary_source_revisions_source_revision_id "
        "ON summary_source_revisions(source_revision_id)"
    )
    op.execute("""
CREATE TABLE research_progress_updates (
 id UUID PRIMARY KEY,
 ownership_scope_id UUID NOT NULL REFERENCES research_scopes(id),
 object_id UUID NOT NULL,
 revision_id UUID NOT NULL,
 status VARCHAR(16) NOT NULL,
 detail_md TEXT NOT NULL,
 contribution_id UUID NOT NULL REFERENCES contribution_envelopes(id),
 created_by_user_id UUID NOT NULL REFERENCES users(id),
 provenance_kind VARCHAR(32) NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 CONSTRAINT fk_research_progress_object_scope FOREIGN KEY (object_id, ownership_scope_id)
  REFERENCES research_objects(id, ownership_scope_id),
 CONSTRAINT fk_research_progress_revision_object FOREIGN KEY (revision_id, object_id)
  REFERENCES object_revisions(id, object_id),
 CONSTRAINT ck_research_progress_status CHECK
  (status IN ('POTENTIAL','PARTIAL','COMPLETE','STALLED','FAILED')),
 CONSTRAINT ck_research_progress_provenance CHECK
  (provenance_kind IN ('HUMAN_DIRECT','AGENT_PROPOSAL','AGENT_DIRECT'))
)
""")
    for column in (
        "ownership_scope_id",
        "object_id",
        "revision_id",
        "contribution_id",
        "created_by_user_id",
    ):
        op.execute(
            f"CREATE INDEX ix_research_progress_updates_{column} "
            f"ON research_progress_updates({column})"
        )


def _create_assurance_tables() -> None:
    op.execute("""
CREATE TABLE revision_endorsements (
 id UUID PRIMARY KEY,
 revision_id UUID NOT NULL REFERENCES object_revisions(id),
 active BOOLEAN NOT NULL,
 rationale TEXT NOT NULL,
 contribution_id UUID NOT NULL REFERENCES contribution_envelopes(id),
 created_by_user_id UUID NOT NULL REFERENCES users(id),
 created_at TIMESTAMP WITH TIME ZONE NOT NULL
)
""")
    for column in ("revision_id", "contribution_id", "created_by_user_id"):
        op.execute(
            f"CREATE INDEX ix_revision_endorsements_{column} ON revision_endorsements({column})"
        )
    op.execute("""
CREATE TABLE correspondence_assessments (
 id UUID PRIMARY KEY,
 revision_id UUID NOT NULL REFERENCES record_revisions(revision_id),
 statement_revision_id UUID NOT NULL REFERENCES statement_revisions(revision_id),
 status VARCHAR(16) NOT NULL,
 rationale TEXT NOT NULL,
 contribution_id UUID NOT NULL REFERENCES contribution_envelopes(id),
 created_by_user_id UUID NOT NULL REFERENCES users(id),
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 CONSTRAINT ck_correspondence_status CHECK
  (status IN ('MATCHES','PARTIAL','MISMATCH','UNASSESSED'))
)
""")
    for column in (
        "revision_id",
        "statement_revision_id",
        "contribution_id",
        "created_by_user_id",
    ):
        op.execute(
            f"CREATE INDEX ix_correspondence_assessments_{column} "
            f"ON correspondence_assessments({column})"
        )


def _create_integrity_triggers() -> None:
    for table in (
        "proof_sketch_revisions",
        "proof_sketch_premises",
        "research_attempt_revisions",
        "attempt_evidence_links",
        "human_note_revisions",
        "research_summary_revisions",
        "summary_source_revisions",
        "research_progress_updates",
        "revision_endorsements",
        "correspondence_assessments",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()"
        )
    op.execute("""
CREATE FUNCTION protect_associated_stream() RETURNS trigger AS $$
BEGIN
IF TG_OP = 'DELETE' OR NEW.object_id IS DISTINCT FROM OLD.object_id OR
 NEW.ownership_scope_id IS DISTINCT FROM OLD.ownership_scope_id OR
 NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id OR
 NEW.created_at IS DISTINCT FROM OLD.created_at
THEN RAISE EXCEPTION 'associated stream identity is immutable'; END IF;
RETURN NEW; END; $$ LANGUAGE plpgsql
""")
    for table in ("human_notes", "research_summaries"):
        op.execute(
            f"CREATE TRIGGER {table}_identity_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_associated_stream()"
        )
    op.execute("""
CREATE FUNCTION protect_research_structure_extension() RETURNS trigger AS $$
DECLARE rev_id uuid; insertion_xid bigint; conclusion_id uuid;
BEGIN
IF TG_TABLE_NAME = 'proof_sketch_premises' THEN rev_id = NEW.sketch_revision_id;
ELSIF TG_TABLE_NAME = 'attempt_evidence_links' THEN rev_id = NEW.attempt_revision_id;
ELSIF TG_TABLE_NAME = 'summary_source_revisions' THEN rev_id = NEW.summary_revision_id;
ELSE rev_id = NEW.revision_id; END IF;
IF TG_TABLE_NAME = 'summary_source_revisions' THEN
 SELECT xmin::text::bigint INTO insertion_xid FROM research_summary_revisions WHERE id = rev_id;
ELSE
 SELECT xmin::text::bigint INTO insertion_xid FROM object_revisions WHERE id = rev_id;
END IF;
IF insertion_xid IS DISTINCT FROM (txid_current() % 4294967296) THEN
 RAISE EXCEPTION 'research structure must be created with its revision';
END IF;
IF TG_TABLE_NAME = 'proof_sketch_premises' THEN
 SELECT conclusion_revision_id INTO conclusion_id FROM proof_sketch_revisions
 WHERE revision_id = NEW.sketch_revision_id;
 IF conclusion_id = NEW.premise_revision_id THEN
  RAISE EXCEPTION 'a conclusion cannot be its own premise';
 END IF;
END IF;
RETURN NEW; END; $$ LANGUAGE plpgsql
""")
    for table in (
        "proof_sketch_revisions",
        "proof_sketch_premises",
        "research_attempt_revisions",
        "attempt_evidence_links",
        "summary_source_revisions",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_insert_boundary BEFORE INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_research_structure_extension()"
        )
    op.execute("""
CREATE FUNCTION validate_research_attempt() RETURNS trigger AS $$
DECLARE target_kind varchar(32); target_number integer; result_number integer;
BEGIN
SELECT ro.kind, target.number INTO target_kind, target_number
FROM research_objects ro JOIN object_revisions target ON target.object_id = ro.id
WHERE target.id = NEW.target_revision_id;
IF target_kind = 'ATTEMPT' THEN RAISE EXCEPTION 'attempts cannot target attempts'; END IF;
IF NEW.result_revision_id IS NOT NULL THEN
 SELECT number INTO result_number FROM object_revisions WHERE id = NEW.result_revision_id;
 IF result_number <= target_number THEN
  RAISE EXCEPTION 'attempt result must be a newer target revision';
 END IF;
END IF;
RETURN NEW; END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER research_attempt_target_valid BEFORE INSERT ON research_attempt_revisions
FOR EACH ROW EXECUTE FUNCTION validate_research_attempt()
""")
    op.execute("""
CREATE FUNCTION validate_structured_record() RETURNS trigger AS $$
DECLARE record_kind varchar(32);
BEGIN
SELECT kind INTO record_kind FROM record_revisions WHERE revision_id = NEW.revision_id;
IF record_kind IN ('PROOF','PROOF_SKETCH') AND
 NOT EXISTS (SELECT 1 FROM proof_sketch_revisions WHERE revision_id = NEW.revision_id)
THEN RAISE EXCEPTION 'proof-sketch revision requires exact structure';
ELSIF record_kind = 'ATTEMPT' AND
 NOT EXISTS (SELECT 1 FROM research_attempt_revisions WHERE revision_id = NEW.revision_id)
THEN RAISE EXCEPTION 'attempt revision requires an exact target';
ELSIF record_kind NOT IN ('PROOF','PROOF_SKETCH') AND
 EXISTS (SELECT 1 FROM proof_sketch_revisions WHERE revision_id = NEW.revision_id)
THEN RAISE EXCEPTION 'proof-sketch structure requires a proof-sketch revision';
ELSIF record_kind <> 'ATTEMPT' AND
 EXISTS (SELECT 1 FROM research_attempt_revisions WHERE revision_id = NEW.revision_id)
THEN RAISE EXCEPTION 'attempt structure requires an attempt revision';
END IF;
RETURN NULL; END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE CONSTRAINT TRIGGER record_revision_structure_complete AFTER INSERT ON record_revisions
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_structured_record()
""")


def downgrade() -> None:
    raise RuntimeError("Research and assurance history is immutable; do not discard it.")
