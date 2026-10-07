"""Immutable, permission-filtered run context manifests for WP-10."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from polycolab.agents import grants as run_grants
from polycolab.artifacts import service as artifact_service
from polycolab.db.models import (
    SqlAgentRun,
    SqlArtifact,
    SqlContextManifest,
    SqlContextManifestArtifact,
    SqlObjectRevision,
    SqlRelationAssertion,
    SqlRunArtifactOutput,
)
from polycolab.entities.enums import RelationType
from polycolab.research.objects import ResearchNotFound
from polycolab.research.records import accessible_revision, project_access, public_condition
from polycolab.research.version_projections import version_reads
from polycolab.research.version_schemas import ObjectVersionRead

MAX_CONTEXT_REVISIONS = 128
MAX_CONTEXT_ARTIFACTS = 32


class ContextInvalid(Exception):
    pass


def _digest(revision_ids: list[str], artifact_ids: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(
            {"version": 2, "revision_ids": revision_ids, "artifact_ids": artifact_ids},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _legacy_digest(revision_ids: list[str]) -> str:
    return hashlib.sha256(json.dumps(revision_ids, separators=(",", ":")).encode()).hexdigest()


def manifest_for_run(session: Session, *, run: SqlAgentRun) -> SqlContextManifest:
    """Build exactly once from supplied revisions plus immediate pinned neighbors."""

    project_access(session, run.project_id, run.requested_by_user_id)
    authority = run_grants.requested(session, run.id)
    if authority is not None:
        run_grants.validate(
            session,
            project_id=run.project_id,
            user_id=run.requested_by_user_id,
            agent_version_id=run.agent_version_id,
            context_ids=[UUID(value) for value in run.requested_context_revision_ids],
            authority=authority,
        )
    existing = session.scalar(select(SqlContextManifest).where(SqlContextManifest.run_id == run.id))
    if existing is not None:
        expected = _digest(existing.revision_ids, existing.artifact_ids)
        legacy = not existing.artifact_ids and existing.digest == _legacy_digest(
            existing.revision_ids
        )
        if (
            existing.project_id != run.project_id
            or existing.requested_by_user_id != run.requested_by_user_id
            or existing.agent_version_id != run.agent_version_id
            or (existing.digest != expected and not legacy)
        ):
            raise ContextInvalid
        manifest_revisions(session, manifest=existing)
        manifest_artifacts(session, manifest=existing)
        return existing
    explicit: list[UUID] = []
    try:
        explicit = [UUID(value) for value in run.requested_context_revision_ids]
    except (TypeError, ValueError) as exc:
        raise ContextInvalid from exc
    if len(set(explicit)) != len(explicit) or len(explicit) > MAX_CONTEXT_REVISIONS:
        raise ContextInvalid
    try:
        explicit_artifacts = [UUID(value) for value in run.requested_context_artifact_ids]
    except (TypeError, ValueError) as exc:
        raise ContextInvalid from exc
    if (
        len(set(explicit_artifacts)) != len(explicit_artifacts)
        or len(explicit_artifacts) > MAX_CONTEXT_ARTIFACTS
        or (explicit_artifacts and authority is not None and authority.destination == "PUBLIC")
    ):
        raise ContextInvalid
    revisions: set[UUID] = set()
    for revision_id in explicit:
        revisions.add(accessible_revision(session, revision_id, run.project_id).id)
    if revisions:
        dependencies = session.scalars(
            select(SqlRelationAssertion.target_revision_id)
            .where(
                or_(
                    SqlRelationAssertion.project_id == run.project_id,
                    public_condition(SqlRelationAssertion.source_revision_id),
                ),
                SqlRelationAssertion.source_revision_id.in_(revisions),
                SqlRelationAssertion.relation_type == RelationType.DEPENDS_ON,
            )
            .distinct()
            .order_by(SqlRelationAssertion.target_revision_id)
            .limit(MAX_CONTEXT_REVISIONS + 1)
        )
        revisions.update(dependencies)
    if len(revisions) > MAX_CONTEXT_REVISIONS:
        raise ContextInvalid
    ordered = sorted(str(value) for value in revisions)
    ordered_artifacts = sorted(str(value) for value in explicit_artifacts)
    # Exact pins only: no current-revision traversal and no cached authorization.
    for revision_id in revisions:
        accessible_revision(
            session,
            revision_id,
            None if authority is not None and authority.destination == "PUBLIC" else run.project_id,
        )
    try:
        for artifact_id in explicit_artifacts:
            artifact_service.read(
                session,
                project_id=run.project_id,
                user_id=run.requested_by_user_id,
                artifact_id=artifact_id,
            )
    except ResearchNotFound as exc:
        raise ContextInvalid from exc
    digest = _digest(ordered, ordered_artifacts)
    value = SqlContextManifest(
        run_id=run.id,
        project_id=run.project_id,
        requested_by_user_id=run.requested_by_user_id,
        agent_version_id=run.agent_version_id,
        revision_ids=ordered,
        artifact_ids=ordered_artifacts,
        digest=digest,
    )
    session.add(value)
    session.flush()
    session.add_all(
        [
            SqlContextManifestArtifact(
                manifest_id=value.id, artifact_id=UUID(artifact_id), position=position
            )
            for position, artifact_id in enumerate(ordered_artifacts)
        ]
    )
    session.commit()
    session.refresh(value)
    return value


def manifest_revisions(
    session: Session, *, manifest: SqlContextManifest
) -> list[SqlObjectRevision]:
    project_access(session, manifest.project_id, manifest.requested_by_user_id)
    try:
        ids = [UUID(value) for value in manifest.revision_ids]
    except (TypeError, ValueError) as exc:
        raise ContextInvalid from exc
    if (
        len(ids) != len(set(ids))
        or len(ids) > MAX_CONTEXT_REVISIONS
        or (
            manifest.digest != _digest(manifest.revision_ids, manifest.artifact_ids)
            and not (
                not manifest.artifact_ids
                and manifest.digest == _legacy_digest(manifest.revision_ids)
            )
        )
    ):
        raise ContextInvalid
    try:
        authority = run_grants.requested(session, manifest.run_id)
        if authority is not None:
            run_grants.validate(
                session,
                project_id=manifest.project_id,
                user_id=manifest.requested_by_user_id,
                agent_version_id=manifest.agent_version_id,
                context_ids=ids,
                authority=authority,
            )
        project_id = (
            None
            if authority is not None and authority.destination == "PUBLIC"
            else manifest.project_id
        )
        return [accessible_revision(session, value, project_id) for value in sorted(ids)]
    except ResearchNotFound as exc:
        raise ContextInvalid from exc


def manifest_object_versions(
    session: Session, *, manifest: SqlContextManifest
) -> list[ObjectVersionRead]:
    """Present exact member-authorized pins using their appropriate content projection.

    This is the owner's context inspection, not the agent tool surface. Tool reads
    add capability-specific clipping of unpinned relationships and private metadata.
    """
    rows = manifest_revisions(session, manifest=manifest)
    authority = run_grants.requested(session, manifest.run_id)
    project_id = (
        manifest.project_id if authority is None or authority.destination == "WORKSPACE" else None
    )
    private = [row for row in rows if project_id is not None and row.project_id == project_id]
    public = [row for row in rows if project_id is None or row.project_id != project_id]
    values = [
        *version_reads(session, private, project_id=project_id, public=False),
        *version_reads(session, public, public=True),
    ]
    by_id = {value.id: value for value in values}
    return [by_id[row.id] for row in rows]


def manifest_artifacts(session: Session, *, manifest: SqlContextManifest) -> list[SqlArtifact]:
    """Return typed exact artifact pins after current scope authorization."""

    project_access(session, manifest.project_id, manifest.requested_by_user_id)
    try:
        ids = [UUID(value) for value in manifest.artifact_ids]
    except (TypeError, ValueError) as exc:
        raise ContextInvalid from exc
    rows = list(
        session.scalars(
            select(SqlContextManifestArtifact)
            .where(SqlContextManifestArtifact.manifest_id == manifest.id)
            .order_by(SqlContextManifestArtifact.position)
        )
    )
    if (
        len(ids) != len(set(ids))
        or len(ids) > MAX_CONTEXT_ARTIFACTS
        or [row.artifact_id for row in rows] != ids
        or (
            manifest.digest != _digest(manifest.revision_ids, manifest.artifact_ids)
            and not (not ids and manifest.digest == _legacy_digest(manifest.revision_ids))
        )
    ):
        raise ContextInvalid
    try:
        for artifact_id in ids:
            artifact_service.read(
                session,
                project_id=manifest.project_id,
                user_id=manifest.requested_by_user_id,
                artifact_id=artifact_id,
            )
        by_id = {
            row.id: row
            for row in session.scalars(select(SqlArtifact).where(SqlArtifact.id.in_(ids)))
        }
        if len(by_id) != len(ids):
            raise ContextInvalid
        return [by_id[artifact_id] for artifact_id in ids]
    except ResearchNotFound as exc:
        raise ContextInvalid from exc


def run_artifacts(
    session: Session, *, run: SqlAgentRun, limit: int | None = None
) -> list[SqlArtifact]:
    """Return committed artifact outputs after current run-sponsor access."""

    if limit is not None and not 1 <= limit <= 50:
        raise ContextInvalid
    query = (
        select(SqlArtifact)
        .join(SqlRunArtifactOutput, SqlRunArtifactOutput.artifact_id == SqlArtifact.id)
        .where(SqlRunArtifactOutput.run_id == run.id)
        .order_by(SqlRunArtifactOutput.created_at, SqlRunArtifactOutput.artifact_id)
    )
    if limit is not None:
        query = query.limit(limit)
    rows = list(session.scalars(query))
    try:
        for artifact in rows:
            artifact_service.read(
                session,
                project_id=run.project_id,
                user_id=run.requested_by_user_id,
                artifact_id=artifact.id,
            )
    except ResearchNotFound as exc:
        raise ContextInvalid from exc
    return rows
