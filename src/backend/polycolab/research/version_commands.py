"""Translate complete wire snapshots into the existing transactional service."""

from uuid import UUID

from polycolab.entities.object_kinds import storage_kind
from polycolab.entities.research import StructuralRole
from polycolab.research.contracts import SnapshotRecordWrite, SnapshotRelationWrite
from polycolab.research.version_schemas import (
    AgentObjectVersionWrite,
    AttemptVersionSnapshot,
    BidirectionalDeclarationCreate,
    EditableVersionSnapshot,
    ObjectVersionDeclarationCreate,
    ProofVersionSnapshot,
    VersionLibraryDestination,
)


def agent_snapshot_command(request: AgentObjectVersionWrite) -> SnapshotRecordWrite:
    project_id = (
        None
        if isinstance(request.destination, VersionLibraryDestination)
        else request.destination.workspace_id
    )
    command = snapshot_command(
        request.snapshot,
        project_id=project_id,
        object_id=request.object_id,
        expected_current_object_version_id=request.expected_current_object_version_id,
    )
    if (
        isinstance(request.destination, VersionLibraryDestination)
        and request.destination.statement_object_version_id not in command.statement_revision_ids
    ):
        raise ValueError("Library destination requires an explicit statement attachment")
    return command


def declaration_command(request: ObjectVersionDeclarationCreate) -> SnapshotRelationWrite:
    project_id = (
        None
        if isinstance(request.destination, VersionLibraryDestination)
        else request.destination.workspace_id
    )
    first, second = (
        (request.first_object_version_id, request.second_object_version_id)
        if isinstance(request, BidirectionalDeclarationCreate)
        else (request.source_object_version_id, request.target_object_version_id)
    )
    return SnapshotRelationWrite(
        project_id=project_id,
        source_revision_id=first,
        target_revision_id=second,
        relation_type=request.relationship_type,
        rationale=request.description or "Declared relationship",
        description=request.description,
    )


def snapshot_command(
    snapshot: EditableVersionSnapshot,
    *,
    project_id: UUID | None,
    object_id: UUID | None = None,
    expected_current_object_version_id: UUID | None = None,
) -> SnapshotRecordWrite:
    def pins(role: StructuralRole) -> list[UUID]:
        return [
            item.target_object_version_id
            for item in sorted(snapshot.structural_relationships, key=lambda r: r.position or 0)
            if item.relationship_type == role
        ]

    proof = None
    attempt = None
    if isinstance(snapshot, ProofVersionSnapshot):
        proof = {
            "conclusion_revision_id": pins(StructuralRole.CONCLUSION)[0],
            "premise_revision_ids": pins(StructuralRole.PREMISE),
            "reported_progress": snapshot.content.reported_progress,
        }
    if isinstance(snapshot, AttemptVersionSnapshot):
        results = pins(StructuralRole.RESULT)
        attempt = {
            "target_revision_id": pins(StructuralRole.TARGET)[0],
            "result_revision_id": results[0] if results else None,
            "outcome": snapshot.content.outcome,
            "findings_md": snapshot.content.findings_md,
            "evidence": [
                {"revision_id": r.target_object_version_id, "role": r.evidence_role}
                for r in sorted(snapshot.structural_relationships, key=lambda r: r.position or 0)
                if r.relationship_type == StructuralRole.EVIDENCE
            ],
        }
    return SnapshotRecordWrite.model_validate(
        {
            "project_id": project_id,
            "object_id": object_id,
            "base_revision_id": expected_current_object_version_id,
            "kind": storage_kind(snapshot.kind),
            "semantic_metadata": {
                "canonical_kind": snapshot.kind,
                **(
                    {
                        "attached_object_ids": [
                            str(value) for value in snapshot.content.attached_object_ids
                        ]
                    }
                    if snapshot.content.attached_object_ids
                    else {}
                ),
                **(
                    {"source_language": snapshot.content.source_language}
                    if snapshot.content.source_language
                    else {}
                ),
                **(
                    {"statement_label": snapshot.content.statement_label or "CLAIM"}
                    if snapshot.kind == "STATEMENT"
                    else {}
                ),
                **(
                    {"proof_direction": snapshot.content.direction}
                    if isinstance(snapshot, ProofVersionSnapshot)
                    else {}
                ),
            },
            **snapshot.content.model_dump(
                include={
                    "title",
                    "content_md",
                    "assumptions_md",
                    "reported_outcome",
                    "explanation_md",
                }
            ),
            "statement_revision_ids": pins(StructuralRole.ATTACHMENT),
            "reason": snapshot.change_summary or "Saved research version",
            "change_summary": snapshot.change_summary,
            "proof_sketch": proof,
            "attempt": attempt,
            "premise_positions": sorted(
                r.position
                for r in snapshot.structural_relationships
                if r.relationship_type == StructuralRole.PREMISE and r.position is not None
            ),
            "evidence_positions": sorted(
                r.position
                for r in snapshot.structural_relationships
                if r.relationship_type == StructuralRole.EVIDENCE and r.position is not None
            ),
        }
    )
