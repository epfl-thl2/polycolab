"""Typed projections of caller-authorized publication snapshots.

Preview, confirmation, and history share this adapter. Content comes from the
selected frozen fields, not today's object or account metadata. Canonical rows
only supply structural identity; this module does not authorize a publication.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.artifacts.contracts import PublishedArtifactVersionRead
from polycolab.catalogue.publication_schemas import PublicationVersionFields
from polycolab.db.models import SqlObjectRevision
from polycolab.research.activity_schemas import (
    ResearchCommentVersionRead,
    ResearchProgressVersionRead,
    ResearchSummaryVersionRevisionRead,
)
from polycolab.research.contracts import PublicationFields
from polycolab.research.objects import ResearchNotFound
from polycolab.research.records import public_condition
from polycolab.research.version_projections import projected_version_reads, relationship_reads


def publication_fields(session: Session, fields: PublicationFields) -> PublicationVersionFields:
    version_ids = {record.revision_id for record in fields.records}
    versions = {
        row.id: row
        for row in session.scalars(
            select(SqlObjectRevision).where(SqlObjectRevision.id.in_(version_ids))
        )
    }
    if versions.keys() != version_ids:
        raise ResearchNotFound
    predecessor_ids = {
        record.base_revision_id for record in fields.records if record.base_revision_id is not None
    }
    visible_predecessors = version_ids | set(
        session.scalars(
            select(SqlObjectRevision.id).where(
                SqlObjectRevision.id.in_(predecessor_ids), public_condition(SqlObjectRevision.id)
            )
        )
    )
    selected = [
        record.model_copy(
            update={
                "base_revision_id": record.base_revision_id
                if record.base_revision_id in visible_predecessors
                else None,
                "author_user_id": None,
                "agent_id": None,
                "sponsor_user_id": None,
            }
        )
        for record in fields.records
    ]
    return PublicationVersionFields(
        reviews=fields.reviews,
        object_versions=projected_version_reads(
            session,
            [versions[record.revision_id] for record in selected],
            selected,
            public=True,
        ),
        summaries=[ResearchSummaryVersionRevisionRead.model_validate(v) for v in fields.summaries],
        comments=[ResearchCommentVersionRead.model_validate(v) for v in fields.comments],
        progress=[ResearchProgressVersionRead.model_validate(v) for v in fields.progress],
        relationships=relationship_reads(
            session, [r.id for r in fields.relations], public=True, released=fields.relations
        ),
        artifacts=[PublishedArtifactVersionRead.from_release(v) for v in fields.artifacts],
    )
