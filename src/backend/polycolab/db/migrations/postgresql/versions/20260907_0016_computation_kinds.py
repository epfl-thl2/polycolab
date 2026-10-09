"""Enable the planned formalization and computation research record kinds."""

from alembic import op

revision = "20260907_computation_kinds"
down_revision = "20260907_verification_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_research_objects_kind", "research_objects", type_="check")
    op.create_check_constraint(
        "ck_research_objects_kind",
        "research_objects",
        "kind IN ('PROBLEM', 'DEFINITION', 'CLAIM', 'PROOF', 'PROOF_SKETCH', 'ATTEMPT', "
        "'COUNTEREXAMPLE', 'NOTE', 'IDEA', 'DISCUSSION', 'FORMALIZATION', 'COMPUTATION')",
    )


def downgrade() -> None:
    raise RuntimeError("Formalization and computation research history is durable.")
