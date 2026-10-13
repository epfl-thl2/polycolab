"""Independent project copies of exact Library statement revisions."""

from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from polycolab.access.actors import Actor
from polycolab.access.authorization import require_human_actor
from polycolab.catalogue.admission import lock_commons
from polycolab.db.models import SqlCatalogueRevision, SqlUser
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import ProjectVisibility
from polycolab.platform import mutation_keys
from polycolab.projects.service import create_project
from polycolab.research import records
from polycolab.research.contracts import ProjectCopyCreate, ProjectCopyRead, SnapshotRecordWrite
from polycolab.research.objects import ResearchNotFound


def create(
    session: Session, *, actor: Actor, payload: ProjectCopyCreate, key: str
) -> ProjectCopyRead:
    require_human_actor(actor, action="copy Library research")
    user_id = actor.human_user_id
    assert user_id is not None
    actor_key = f"human:{user_id}"
    body = payload.model_dump(mode="json")
    if "project_name" not in payload.model_fields_set:
        # Historical default belongs only to retry serialization, never new names.
        body["project_name"] = "Research workspace"
    try:
        mutation_keys.lock_key(session, actor_key, "project.copy", key)
        receipt = mutation_keys.receipt(
            session,
            actor_key,
            "project.copy",
            key,
            body,
            authorize=lambda stored: records.project_access(
                session, UUID(stored.resource_ids[0]), user_id, write=True
            ),
        )
        if receipt:
            project_id, object_id, revision_id, source_id = map(UUID, receipt.resource_ids)
            records.project_access(session, project_id, user_id, write=True)
        else:
            destination_id = payload.project_id
            if destination_id is None:
                user = session.get(SqlUser, user_id)
                assert user is not None
                destination_id = create_project(
                    SqlAlchemyTransaction(session),
                    creator=user,
                    name=payload.project_name,
                    description=None,
                    visibility=ProjectVisibility(payload.project_visibility),
                    commit=False,
                ).id
            project_id = destination_id
            records.project_access(session, project_id, user_id, write=True)
            lock_commons(session)
            source = records.public_revision(session, payload.revision_id)
            if session.get(SqlCatalogueRevision, source.id) is None:
                raise ResearchNotFound
            source_read = records.public_record_read(session, source)
            copied = records.write_record(
                session,
                actor=actor,
                payload=SnapshotRecordWrite(
                    project_id=project_id,
                    kind=source_read.kind,
                    title=source_read.title,
                    content_md=source_read.content_md,
                    assumptions_md=source_read.assumptions_md,
                    explanation_md=source_read.explanation_md,
                    reported_outcome=cast(
                        Literal["UNASSESSED", "IN_PROGRESS", "FAILED", "PARTIAL", "SUCCEEDED"]
                        | None,
                        source_read.reported_outcome,
                    ),
                    statement_revision_ids=[source.id],
                    reason=f"Copied from Library version {source.id}",
                    change_summary=f"Copied from Library version {source.id}",
                    premise_positions=[],
                    evidence_positions=[],
                ),
                key=f"copy:{uuid4()}",
                commit=False,
            )
            assert copied.revision_id is not None
            object_id, revision_id, source_id = copied.id, copied.revision_id, source.id
            mutation_keys.save(
                session,
                actor_key,
                "project.copy",
                key,
                body,
                [project_id, object_id, revision_id, source_id],
            )
        result = ProjectCopyRead(
            project_id=project_id,
            object_id=object_id,
            revision_id=revision_id,
            source_revision_id=source_id,
        )
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
