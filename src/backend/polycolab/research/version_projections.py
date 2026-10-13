"""Current wire projections over authorized records and frozen public releases."""

from collections.abc import Sequence
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.db.models import (
    SqlObjectRevision,
    SqlPublicationManifest,
    SqlPublicationRelation,
    SqlResearchObject,
)
from polycolab.db.models.relationships import SqlObjectVersionRelationship
from polycolab.db.stores.research import SqlResearchReadStore
from polycolab.entities.enums import ContributionActorKind
from polycolab.entities.object_kinds import canonical_kind
from polycolab.entities.research import StructuralRole
from polycolab.research import records
from polycolab.research.contracts import PublishedRelationRead, RecordRead
from polycolab.research.objects import ResearchNotFound
from polycolab.research.version_schemas import (
    MemberVersionedObjectRead,
    ObjectVersionRead,
    ObjectVersionRelationshipRead,
    PublicVersionedObjectRead,
    VersionAuthorshipRead,
    VersionedObjectRead,
)

_version_adapter: TypeAdapter[ObjectVersionRead] = TypeAdapter(ObjectVersionRead)
_relationship_adapter: TypeAdapter[ObjectVersionRelationshipRead] = TypeAdapter(
    ObjectVersionRelationshipRead
)


def relationship_reads(
    session: Session,
    relationship_ids: Sequence[UUID],
    *,
    public: bool,
    released: Sequence[PublishedRelationRead] | None = None,
) -> list[ObjectVersionRelationshipRead]:
    """Project caller-authorized declarations; never infer access from endpoints."""
    snapshots = SqlResearchReadStore(session).relationships(relationship_ids)
    frozen = {row.id: row for row in released} if released is not None else {}
    if public and relationship_ids and released is None:
        manifests = session.scalars(
            select(SqlPublicationManifest)
            .join(
                SqlPublicationRelation,
                SqlPublicationRelation.manifest_id == SqlPublicationManifest.id,
            )
            .where(SqlPublicationRelation.relation_id.in_(relationship_ids))
            .order_by(
                SqlPublicationManifest.created_at,
                SqlPublicationManifest.id,
            )
        ).unique()
        for manifest in manifests:
            published = manifest.public_fields.get("relations", [])
            if not isinstance(published, list):
                raise ResearchNotFound
            for value in published:
                parsed = PublishedRelationRead.model_validate(value)
                if parsed.id in relationship_ids:
                    frozen.setdefault(parsed.id, parsed)
    result = []
    for relationship_id in relationship_ids:
        if relationship_id not in snapshots:
            raise ResearchNotFound
        value = _relationship_adapter.validate_python(
            snapshots[relationship_id], from_attributes=True
        )
        if public:
            attribution = value.authorship.model_copy(
                update={
                    "contribution_id": None,
                    "author_user_id": None,
                    "agent_id": None,
                    "sponsor_user_id": None,
                }
            )
            if saved := frozen.get(relationship_id):
                if value.direction == "BIDIRECTIONAL":
                    matches = {value.first_object_version_id, value.second_object_version_id} == {
                        saved.source_revision_id,
                        saved.target_revision_id,
                    }
                else:
                    matches = (
                        value.source_object_version_id == saved.source_revision_id
                        and value.target_object_version_id == saved.target_revision_id
                    )
                if not matches or value.relationship_type != saved.relation_type:
                    raise ResearchNotFound
                attribution = attribution.model_copy(
                    update={
                        "author_display_name": saved.author_display_name,
                        "actor_kind": ContributionActorKind(saved.actor_kind),
                        "agent_display_name": saved.agent_display_name,
                    }
                )
                value = value.model_copy(
                    update={"description": saved.rationale, "created_at": saved.created_at}
                )
            value = value.model_copy(update={"ownership_scope_id": None, "authorship": attribution})
        result.append(value)
    return result


def object_read(session: Session, obj: SqlResearchObject, *, public: bool) -> VersionedObjectRead:
    if public:
        selected = session.scalar(
            select(SqlObjectRevision)
            .where(
                SqlObjectRevision.object_id == obj.id,
                records.public_condition(SqlObjectRevision.id),
            )
            .order_by(SqlObjectRevision.number.desc())
            .limit(1)
        )
    else:
        selected = (
            session.get(SqlObjectRevision, obj.current_revision_id)
            if obj.current_revision_id
            else None
        )
    if selected is None:
        raise ResearchNotFound
    version = version_reads(session, [selected], project_id=obj.project_id, public=public)[0]
    if public:
        return PublicVersionedObjectRead(
            id=obj.id,
            kind=canonical_kind(obj.kind),
            created_at=obj.created_at,
            current_object_version_id=version.id,
            current_object_version=version,
        )
    identity = SqlResearchReadStore(session).objects([obj.id])[obj.id]
    return MemberVersionedObjectRead(
        id=obj.id,
        kind=canonical_kind(obj.kind),
        created_at=obj.created_at,
        current_object_version_id=version.id,
        current_object_version=version,
        ownership_scope_id=obj.ownership_scope_id,
        authorship=VersionAuthorshipRead.model_validate(identity.authorship),
    )


def version_reads(
    session: Session,
    versions: Sequence[SqlObjectRevision],
    *,
    project_id: UUID | None = None,
    public: bool,
) -> list[ObjectVersionRead]:
    """Callers authorize member selections; public selections are rechecked here.

    Public content and attribution come exclusively from the release-aware reader.
    Canonical relationship rows supply IDs and original positions, never extra pins.
    """
    selected = (
        records.public_record_reads(session, versions)
        if public
        else records.record_reads(session, versions, project_id)
    )
    return projected_version_reads(session, versions, selected, public=public)


def projected_version_reads(
    session: Session,
    versions: Sequence[SqlObjectRevision],
    selected: Sequence[RecordRead],
    *,
    public: bool,
) -> list[ObjectVersionRead]:
    """Adapt already authorized projections without replacing frozen fields."""
    relationships: dict[UUID, list[SqlObjectVersionRelationship]] = {}
    for relationship in session.scalars(
        select(SqlObjectVersionRelationship)
        .where(
            SqlObjectVersionRelationship.binding == "STRUCTURAL",
            SqlObjectVersionRelationship.source_object_version_id.in_([v.id for v in versions]),
        )
        .order_by(
            SqlObjectVersionRelationship.relationship_type,
            SqlObjectVersionRelationship.position,
            SqlObjectVersionRelationship.target_object_version_id,
        )
    ):
        assert relationship.source_object_version_id is not None
        relationships.setdefault(relationship.source_object_version_id, []).append(relationship)
    attachment_versions = {
        target for record in selected for target in record.statement_revision_ids
    }
    attachment_objects: dict[UUID, UUID] = (
        {
            version_id: object_id
            for version_id, object_id in session.execute(
                select(SqlObjectRevision.id, SqlObjectRevision.object_id).where(
                    SqlObjectRevision.id.in_(attachment_versions)
                )
            )
        }
        if attachment_versions
        else {}
    )
    result = []
    for row, record in zip(versions, selected, strict=True):
        if row.id != record.revision_id or row.object_id != record.object_id:
            raise ResearchNotFound
        authorship = {
            "contribution_id": None if public else row.contribution_id,
            "actor_kind": record.actor_kind,
            "author_display_name": record.author_display_name,
            "author_user_id": None if public else record.author_user_id,
            "author_username": record.author_username,
            "agent_id": None if public else record.agent_id,
            "sponsor_user_id": None if public else record.sponsor_user_id,
            "sponsor_username": record.sponsor_username,
            "agent_display_name": record.agent_display_name,
        }
        expected = {(r.role.value, r.target_version_id) for r in record.structural_relationships}
        pins = [
            r
            for r in relationships.get(row.id, [])
            if (r.relationship_type, r.target_object_version_id) in expected
        ]
        if {(r.relationship_type, r.target_object_version_id) for r in pins} != expected:
            raise ResearchNotFound
        content: dict[str, object] = {
            "title": record.title,
            "content_md": record.content_md,
            "assumptions_md": record.assumptions_md,
            "reported_outcome": record.reported_outcome,
            "explanation_md": record.explanation_md,
        }
        language = record.semantic_metadata.get("source_language") or {
            "COMPUTATION": "PYTHON",
            "FORMALIZATION": "LEAN",
        }.get(record.kind.value)
        if language:
            content["source_language"] = language
        if canonical_kind(record.kind).value in {"NOTE", "ATTEMPT"}:
            attached = record.semantic_metadata.get("attached_object_ids", [])
            ids = {str(value) for value in attached} if isinstance(attached, list) else set()
            ids.update(
                str(attachment_objects[target])
                for target in record.statement_revision_ids
                if target in attachment_objects
            )
            if record.attempt:
                ids.add(str(record.attempt.target_object_id))
            content["attached_object_ids"] = sorted(ids)
        if canonical_kind(record.kind).value == "STATEMENT":
            content["statement_label"] = record.semantic_metadata.get("statement_label", "CLAIM")
        if record.kind.value in {"PROOF", "PROOF_SKETCH"}:
            content["direction"] = record.semantic_metadata.get(
                "proof_direction", "SUPPORTS" if record.proof_sketch else None
            )
            content["reported_progress"] = (
                record.proof_sketch.reported_progress if record.proof_sketch else None
            )
        if record.kind.value == "ATTEMPT":
            content["outcome"] = record.attempt.outcome if record.attempt else None
            content["findings_md"] = record.attempt.findings_md if record.attempt else None
        result.append(
            _version_adapter.validate_python(
                {
                    "id": record.revision_id,
                    "object_id": record.object_id,
                    "kind": canonical_kind(record.kind),
                    "legacy_kind": record.kind.value
                    if not record.semantic_metadata.get("canonical_kind")
                    and canonical_kind(record.kind).value != record.kind.value
                    else None,
                    "number": record.number,
                    "previous_object_version_id": record.base_revision_id,
                    "schema_version": record.schema_version,
                    "change_summary": record.rationale,
                    "authorship": authorship,
                    "created_at": record.created_at,
                    "content": content,
                    "catalogue": {
                        "entry_id": record.catalogue_entry_id,
                        "source": record.catalogue_source,
                        "reported_status": record.catalogue_reported_status,
                        "suggestion": {
                            **record.suggestion.model_dump(exclude={"base_revision_id"}),
                            "expected_current_object_version_id": (
                                record.suggestion.base_revision_id
                            ),
                        }
                        if record.suggestion
                        else None,
                    }
                    if record.catalogue_entry_id or record.suggestion
                    else None,
                    "legacy_unstructured": record.attempt is None,
                    "structural_relationships": [
                        {
                            "id": r.id,
                            "direction": "UNIDIRECTIONAL",
                            "relationship_type": StructuralRole(r.relationship_type),
                            "binding": "STRUCTURAL",
                            "ownership_scope_id": None if public else r.ownership_scope_id,
                            "authorship": authorship,
                            "created_at": record.created_at,
                            "description": r.description,
                            "source_object_version_id": row.id,
                            "target_object_version_id": r.target_object_version_id,
                            "position": r.position,
                            "evidence_role": r.evidence_role,
                        }
                        for r in pins
                    ],
                }
            )
        )
    return result
