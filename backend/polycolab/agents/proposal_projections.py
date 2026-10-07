"""Read historical proposal intent without rewriting its stored payload.

Call only after authorizing proposal review. Historical empty text and inherited
metadata are retained exactly; this read projection is not a new-write validator.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.agents.proposals import (
    CreateCommentPayload,
    CreateObjectPayload,
    CreateRelationPayload,
    CreateRevisionPayload,
    validate_change,
)
from polycolab.db.models import SqlObjectRevision
from polycolab.entities.enums import RelationType
from polycolab.entities.object_kinds import canonical_kind
from polycolab.research.objects import revision_in_project
from polycolab.research.records import record_read


def proposal_payload_read(
    session: Session, *, project_id: UUID, payload: dict[str, object]
) -> dict[str, Any]:
    value = validate_change(payload)
    if isinstance(value, CreateCommentPayload):
        return {
            "kind": "CREATE_COMMENT",
            "object_id": str(value.object_id),
            "object_version_id": str(value.revision_id),
            "body_md": value.body_md,
        }
    if isinstance(value, CreateRelationPayload):
        relationship: dict[str, Any] = {
            "relationship_type": value.relation_type.value,
            "description": value.rationale,
        }
        if value.relation_type is RelationType.EQUIVALENT_TO:
            first, second = sorted((value.source_revision_id, value.target_revision_id))
            relationship.update(
                direction="BIDIRECTIONAL",
                first_object_version_id=str(first),
                second_object_version_id=str(second),
            )
        else:
            relationship.update(
                direction="UNIDIRECTIONAL",
                source_object_version_id=str(value.source_revision_id),
                target_object_version_id=str(value.target_revision_id),
            )
        return {"kind": "CREATE_RELATIONSHIP", "relationship": relationship}
    if not isinstance(value, (CreateObjectPayload, CreateRevisionPayload)):
        return value.model_dump(mode="json")

    content: dict[str, Any] = {
        "title": value.title,
        "content_md": value.content_md,
        "assumptions_md": "",
        "reported_outcome": None,
        "explanation_md": None,
    }
    attachments: set[UUID] = set()
    if isinstance(value, CreateRevisionPayload):
        base = revision_in_project(
            session,
            project_id=project_id,
            revision_id=value.base_revision_id,
            object_id=value.object_id,
        )
        old = record_read(session, base, project_id)
        kind = old.kind.value
        content.update(
            assumptions_md=old.assumptions_md,
            reported_outcome=old.reported_outcome,
            explanation_md=old.explanation_md,
        )
        attachments.update(old.statement_revision_ids)
        result: dict[str, Any] = {
            "kind": "CREATE_OBJECT_VERSION",
            "object_id": str(value.object_id),
            "expected_current_object_version_id": str(value.base_revision_id),
        }
    else:
        kind = value.object_kind.value
        result = {"kind": "CREATE_OBJECT"}
    pins: list[dict[str, Any]] = []
    if kind in {"PROOF", "PROOF_SKETCH"}:
        content["reported_progress"] = None
    if kind == "ATTEMPT":
        content.update(outcome=None, findings_md=None)

    def pin(role: str, target: UUID, **extra: object) -> None:
        pins.append({"relationship_type": role, "target_object_version_id": str(target), **extra})

    if value.proof_sketch is not None:
        proof = value.proof_sketch
        content["reported_progress"] = proof.reported_progress.value
        content["direction"] = "SUPPORTS"
        pin("CONCLUSION", proof.conclusion_revision_id)
        attachments.update((proof.conclusion_revision_id, *proof.premise_revision_ids))
        for position, target in enumerate(proof.premise_revision_ids):
            pin("PREMISE", target, position=position)
    if value.attempt is not None:
        attempt = value.attempt
        content.update(outcome=attempt.outcome.value, findings_md=attempt.findings_md)
        pin("TARGET", attempt.target_revision_id)
        if attempt.result_revision_id is not None:
            pin("RESULT", attempt.result_revision_id)
        for position, evidence in enumerate(attempt.evidence):
            pin(
                "EVIDENCE",
                evidence.revision_id,
                position=position,
                evidence_role=evidence.role.value,
            )
    for target in sorted(attachments):
        pin("ATTACHMENT", target)
    if canonical_kind(kind).value in {"NOTE", "ATTEMPT"}:
        context_versions = set(attachments)
        if value.attempt:
            context_versions.add(value.attempt.target_revision_id)
        object_ids = {
            str(object_id)
            for object_id in session.scalars(
                select(SqlObjectRevision.object_id).where(
                    SqlObjectRevision.id.in_(context_versions)
                )
            )
        }
        if object_ids:
            content["attached_object_ids"] = sorted(object_ids)
    result["snapshot"] = {
        "kind": canonical_kind(kind),
        "content": content,
        "structural_relationships": pins,
        "change_summary": value.rationale,
    }
    return result
