"""Immutable artifact pins for a workspace run, with current membership checks."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.access.authorization import ProjectNotFound
from polycolab.artifacts import service as artifact_service
from polycolab.db.models import (
    SqlAgentRun,
    SqlArtifact,
    SqlContextManifest,
    SqlContextManifestArtifact,
)
from polycolab.projects.access import project_access

MAX_CONTEXT_ARTIFACTS = 32


class ContextInvalid(Exception):
    pass


def _digest(artifact_ids: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(
            {"version": 3, "artifact_ids": artifact_ids},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def manifest_for_run(session: Session, *, run: SqlAgentRun) -> SqlContextManifest:
    project_access(session, run.project_id, run.requested_by_user_id)
    existing = session.scalar(select(SqlContextManifest).where(SqlContextManifest.run_id == run.id))
    if existing is not None:
        if (
            existing.project_id != run.project_id
            or existing.requested_by_user_id != run.requested_by_user_id
            or existing.agent_version_id != run.agent_version_id
        ):
            raise ContextInvalid
        manifest_artifacts(session, manifest=existing)
        return existing
    try:
        ids = [UUID(value) for value in run.requested_context_artifact_ids]
    except (TypeError, ValueError) as exc:
        raise ContextInvalid from exc
    if len(set(ids)) != len(ids) or len(ids) > MAX_CONTEXT_ARTIFACTS:
        raise ContextInvalid
    try:
        for artifact_id in ids:
            artifact_service.read(
                session,
                project_id=run.project_id,
                user_id=run.requested_by_user_id,
                artifact_id=artifact_id,
            )
    except ProjectNotFound as exc:
        raise ContextInvalid from exc
    ordered = sorted(str(value) for value in ids)
    value = SqlContextManifest(
        run_id=run.id,
        project_id=run.project_id,
        requested_by_user_id=run.requested_by_user_id,
        agent_version_id=run.agent_version_id,
        artifact_ids=ordered,
        digest=_digest(ordered),
    )
    session.add(value)
    session.flush()
    session.add_all(
        SqlContextManifestArtifact(
            manifest_id=value.id, artifact_id=UUID(artifact_id), position=position
        )
        for position, artifact_id in enumerate(ordered)
    )
    session.commit()
    session.refresh(value)
    return value


def manifest_artifacts(session: Session, *, manifest: SqlContextManifest) -> list[SqlArtifact]:
    """Validate exact pins and authorize each artifact against current membership."""
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
        or manifest.digest != _digest(manifest.artifact_ids)
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
    except ProjectNotFound as exc:
        raise ContextInvalid from exc
