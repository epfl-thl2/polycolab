"""Exact proof structures and bounded dependency-cycle validation."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from polycolab.db.models import (
    SqlObjectRevision,
    SqlProofSketchPremise,
    SqlProofSketchRevision,
    SqlStatementRevision,
)
from polycolab.db.models.research import SqlProofSketchMetadata
from polycolab.db.stores.relationships import add_structural_relationship
from polycolab.entities.enums import ResearchObjectKind
from polycolab.entities.research import StructuralRole
from polycolab.research.contracts import ProofStructureRead
from polycolab.research.schemas import ProofStructureRequest
from polycolab.workspaces.service import DomainConflict

MAX_DEPENDENCY_EDGES = 10_000


def require_structure(kind: ResearchObjectKind, payload: ProofStructureRequest | None) -> None:
    if (kind in {ResearchObjectKind.PROOF, ResearchObjectKind.PROOF_SKETCH}) != (
        payload is not None
    ):
        raise DomainConflict("proof structure is required exactly for proof-sketch records")


def validate_structure(
    session: Session,
    *,
    project_id: UUID | None,
    kind: ResearchObjectKind,
    payload: ProofStructureRequest,
) -> None:
    """Reject malformed or cyclic exact-statement dependency sets.

    The caller holds the commons graph-mutation lock. Private dependency graphs
    include their workspace and the public graph, but never another workspace.
    """

    from polycolab.research.records import accessible_revision, public_condition

    if kind not in {ResearchObjectKind.PROOF, ResearchObjectKind.PROOF_SKETCH}:
        raise DomainConflict("proof structure requires a proof-sketch record")
    for revision_id in [payload.conclusion_revision_id, *payload.premise_revision_ids]:
        accessible_revision(session, revision_id, project_id)
        if session.get(SqlStatementRevision, revision_id) is None:
            raise DomainConflict("proof conclusions and premises must be statements")

    proof_record = SqlObjectRevision
    visibility = public_condition(proof_record.id)
    if project_id is not None:
        visibility = or_(proof_record.project_id == project_id, visibility)
    rows = list(
        session.execute(
            select(
                SqlProofSketchRevision.conclusion_revision_id,
                SqlProofSketchPremise.premise_revision_id,
            )
            .join(
                SqlProofSketchPremise,
                SqlProofSketchPremise.sketch_revision_id == SqlProofSketchRevision.revision_id,
            )
            .join(proof_record, proof_record.id == SqlProofSketchRevision.revision_id)
            .where(visibility)
            .limit(MAX_DEPENDENCY_EDGES + 1)
        )
    )
    if len(rows) > MAX_DEPENDENCY_EDGES:
        raise DomainConflict("proof dependency traversal limit exceeded")
    outgoing: dict[UUID, set[UUID]] = {}
    for conclusion_id, premise_id in rows:
        outgoing.setdefault(conclusion_id, set()).add(premise_id)

    # New edges are conclusion -> premise. A cycle exists exactly when a new
    # premise already reaches the conclusion in the visible dependency graph.
    for premise_id in payload.premise_revision_ids:
        pending = [premise_id]
        visited: set[UUID] = set()
        while pending:
            current = pending.pop()
            if current == payload.conclusion_revision_id:
                raise DomainConflict("cyclic proof prerequisites")
            if current in visited:
                continue
            visited.add(current)
            if len(visited) > MAX_DEPENDENCY_EDGES:
                raise DomainConflict("proof dependency traversal limit exceeded")
            pending.extend(outgoing.get(current, ()))


def add_structure(
    session: Session,
    *,
    revision_id: UUID,
    payload: ProofStructureRequest,
    positions: list[int] | None = None,
) -> SqlProofSketchRevision:
    proof = SqlProofSketchMetadata(
        revision_id=revision_id,
        reported_progress=payload.reported_progress,
    )
    session.add(proof)
    session.flush()
    add_structural_relationship(
        session,
        source_object_version_id=revision_id,
        target_object_version_id=payload.conclusion_revision_id,
        relationship_type=StructuralRole.CONCLUSION,
    )
    for position, premise_id in enumerate(payload.premise_revision_ids):
        add_structural_relationship(
            session,
            source_object_version_id=revision_id,
            target_object_version_id=premise_id,
            relationship_type=StructuralRole.PREMISE,
            position=positions[position] if positions is not None else position,
        )
    session.flush()
    result = session.get(SqlProofSketchRevision, revision_id)
    assert result is not None
    return result


def structure_read(
    session: Session, revision_id: UUID, project_id: UUID | None
) -> ProofStructureRead | None:
    from polycolab.research.records import accessible_revision

    proof = session.get(SqlProofSketchRevision, revision_id)
    if proof is None:
        return None
    premises = list(
        session.scalars(
            select(SqlProofSketchPremise.premise_revision_id)
            .where(SqlProofSketchPremise.sketch_revision_id == revision_id)
            .order_by(SqlProofSketchPremise.position)
        )
    )
    for dependency_id in [proof.conclusion_revision_id, *premises]:
        accessible_revision(session, dependency_id, project_id)
    return ProofStructureRead(
        sketch_revision_id=revision_id,
        conclusion_revision_id=proof.conclusion_revision_id,
        premise_revision_ids=premises,
        reported_progress=proof.reported_progress,
    )
