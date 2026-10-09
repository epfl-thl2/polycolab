"""Batch materialization of complete immutable research versions."""

from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from polycolab.db.converters import research as converter
from polycolab.db.errors import persistence_boundary
from polycolab.db.models import (
    SqlContributionEnvelope,
    SqlExternalAgentCredential,
    SqlExternalAgentIdentity,
    SqlObjectRevision,
    SqlPlatformAgentVersion,
    SqlProofSketchRevision,
    SqlRecordRevision,
    SqlResearchAttemptRevision,
    SqlResearchObject,
    SqlStatementRevision,
    SqlUser,
)
from polycolab.db.models.relationships import SqlObjectVersionRelationship
from polycolab.entities.research import ObjectVersionRelationship as RelationshipSnapshot
from polycolab.entities.research import ResearchObjectVersion
from polycolab.research.store import ResearchObjectSnapshot


class SqlResearchReadStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    @persistence_boundary
    def relationships(self, relationship_ids: Sequence[UUID]) -> dict[UUID, RelationshipSnapshot]:
        if len(relationship_ids) > 128:
            raise ValueError("research snapshot batch exceeds 128 relationships")
        if not relationship_ids:
            return {}
        result: dict[UUID, RelationshipSnapshot] = {}
        for row, envelope, author, external, platform in self._session.execute(
            select(
                SqlObjectVersionRelationship,
                SqlContributionEnvelope,
                SqlUser,
                SqlExternalAgentIdentity,
                SqlPlatformAgentVersion,
            )
            .join(
                SqlContributionEnvelope,
                SqlContributionEnvelope.id == SqlObjectVersionRelationship.contribution_id,
            )
            .join(SqlUser, SqlUser.id == SqlObjectVersionRelationship.created_by_user_id)
            .outerjoin(
                SqlExternalAgentCredential,
                SqlExternalAgentCredential.id == SqlContributionEnvelope.external_credential_id,
            )
            .outerjoin(
                SqlExternalAgentIdentity,
                SqlExternalAgentIdentity.id
                == func.coalesce(
                    SqlContributionEnvelope.external_agent_id, SqlExternalAgentCredential.agent_id
                ),
            )
            .outerjoin(
                SqlPlatformAgentVersion,
                SqlPlatformAgentVersion.id == SqlContributionEnvelope.agent_version_id,
            )
            .where(SqlObjectVersionRelationship.id.in_(relationship_ids))
        ):
            result[row.id] = converter.relationship(
                row,
                converter.attribution(
                    envelope,
                    author,
                    agent_id=external.id if external else None,
                    agent_display_name=external.name
                    if external
                    else (platform.display_name if platform else None),
                ),
            )
        return result

    @persistence_boundary
    def objects(self, object_ids: Sequence[UUID]) -> dict[UUID, ResearchObjectSnapshot]:
        if len(object_ids) > 128:
            raise ValueError("research snapshot batch exceeds 128 objects")
        if not object_ids:
            return {}
        result: dict[UUID, ResearchObjectSnapshot] = {}
        for obj, envelope, author, external, platform in self._session.execute(
            select(
                SqlResearchObject,
                SqlContributionEnvelope,
                SqlUser,
                SqlExternalAgentIdentity,
                SqlPlatformAgentVersion,
            )
            .join(
                SqlContributionEnvelope,
                SqlContributionEnvelope.id == SqlResearchObject.contribution_id,
            )
            .join(SqlUser, SqlUser.id == SqlResearchObject.created_by_user_id)
            .outerjoin(
                SqlExternalAgentCredential,
                SqlExternalAgentCredential.id == SqlContributionEnvelope.external_credential_id,
            )
            .outerjoin(
                SqlExternalAgentIdentity,
                SqlExternalAgentIdentity.id
                == func.coalesce(
                    SqlContributionEnvelope.external_agent_id, SqlExternalAgentCredential.agent_id
                ),
            )
            .outerjoin(
                SqlPlatformAgentVersion,
                SqlPlatformAgentVersion.id == SqlContributionEnvelope.agent_version_id,
            )
            .where(SqlResearchObject.id.in_(object_ids))
        ):
            result[obj.id] = converter.research_object(
                obj,
                converter.attribution(
                    envelope,
                    author,
                    agent_id=external.id if external else None,
                    agent_display_name=external.name
                    if external
                    else (platform.display_name if platform else None),
                ),
            )
        return result

    @persistence_boundary
    def versions(self, version_ids: Sequence[UUID]) -> dict[UUID, ResearchObjectVersion]:
        if not version_ids:
            return {}
        if len(version_ids) > 128:
            raise ValueError("research snapshot batch exceeds 128 versions")
        session = self._session
        rows = session.execute(
            select(SqlObjectRevision, SqlResearchObject, SqlContributionEnvelope, SqlUser)
            .join(SqlResearchObject, SqlResearchObject.id == SqlObjectRevision.object_id)
            .join(
                SqlContributionEnvelope,
                SqlContributionEnvelope.id == SqlObjectRevision.contribution_id,
            )
            .join(SqlUser, SqlUser.id == SqlObjectRevision.created_by_user_id)
            .where(SqlObjectRevision.id.in_(version_ids))
        ).all()
        statements = {
            row.revision_id: row
            for row in session.scalars(
                select(SqlStatementRevision).where(
                    SqlStatementRevision.revision_id.in_(version_ids)
                )
            )
        }
        records = {
            row.revision_id: row
            for row in session.scalars(
                select(SqlRecordRevision).where(SqlRecordRevision.revision_id.in_(version_ids))
            )
        }
        proofs = {
            row.revision_id: row
            for row in session.scalars(
                select(SqlProofSketchRevision).where(
                    SqlProofSketchRevision.revision_id.in_(version_ids)
                )
            )
        }
        attempts = {
            row.revision_id: row
            for row in session.scalars(
                select(SqlResearchAttemptRevision).where(
                    SqlResearchAttemptRevision.revision_id.in_(version_ids)
                )
            )
        }
        relationships: dict[UUID, list[SqlObjectVersionRelationship]] = defaultdict(list)
        for relationship in session.scalars(
            select(SqlObjectVersionRelationship)
            .where(
                SqlObjectVersionRelationship.source_object_version_id.in_(version_ids),
                SqlObjectVersionRelationship.binding == "STRUCTURAL",
            )
            .order_by(
                SqlObjectVersionRelationship.relationship_type,
                SqlObjectVersionRelationship.position,
                SqlObjectVersionRelationship.target_object_version_id,
            )
        ):
            assert relationship.source_object_version_id is not None
            relationships[relationship.source_object_version_id].append(relationship)
        credentials = {
            credential.id: credential.agent_id
            for credential in session.scalars(
                select(SqlExternalAgentCredential).where(
                    SqlExternalAgentCredential.id.in_(
                        [
                            envelope.external_credential_id
                            for _, _, envelope, _ in rows
                            if envelope.external_credential_id
                        ]
                    )
                )
            )
        }
        agent_ids = {
            envelope.external_agent_id or credentials.get(envelope.external_credential_id)
            for _, _, envelope, _ in rows
        } - {None}
        agents = {
            agent.id: agent.name
            for agent in session.scalars(
                select(SqlExternalAgentIdentity).where(SqlExternalAgentIdentity.id.in_(agent_ids))
            )
        }
        platforms = {
            agent.id: agent.display_name
            for agent in session.scalars(
                select(SqlPlatformAgentVersion).where(
                    SqlPlatformAgentVersion.id.in_(
                        [
                            envelope.agent_version_id
                            for _, _, envelope, _ in rows
                            if envelope.agent_version_id
                        ]
                    )
                )
            )
        }
        result: dict[UUID, ResearchObjectVersion] = {}
        for revision, obj, envelope, author in rows:
            metadata = statements.get(revision.id) or records.get(revision.id)
            if metadata is None:
                raise ValueError("research version has no typed content")
            identity = envelope.external_agent_id or credentials.get(
                envelope.external_credential_id
            )
            result[revision.id] = converter.version(
                revision,
                obj,
                metadata,
                converter.attribution(
                    envelope,
                    author,
                    agent_id=identity,
                    agent_display_name=(agents.get(identity) if identity else None)
                    or platforms.get(envelope.agent_version_id),
                ),
                relationships[revision.id],
                proof=proofs.get(revision.id),
                attempt=attempts.get(revision.id),
            )
        return result
