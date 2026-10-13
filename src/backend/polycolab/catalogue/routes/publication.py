"""Selective publication preview, confirmation, and exact public history."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from polycolab.app.access import research_access
from polycolab.app.dependencies import CurrentActor, DbSession
from polycolab.artifacts.routes.private import artifact_storage
from polycolab.artifacts.storage import ArtifactIntegrity, ArtifactStorageError
from polycolab.catalogue import publication
from polycolab.catalogue.publication_projections import publication_fields
from polycolab.catalogue.publication_schemas import (
    PublicationVersionConfirm,
    PublicationVersionManifestPage,
    PublicationVersionManifestRead,
    PublicationVersionPreview,
    PublicationVersionSelection,
    PublicPublicationVersionManifestRead,
    version_envelope,
)
from polycolab.catalogue.routes.catalogue import RetryKey, no_store
from polycolab.db.models import SqlArtifact
from polycolab.entities.enums import ArtifactState
from polycolab.projects.service import DomainConflict

router = APIRouter(prefix="/api/v1", tags=["publication"], dependencies=[Depends(no_store)])
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=200)]


def _verify_artifact_bytes(request: Request, artifact_ids: list[UUID]) -> frozenset[UUID]:
    if not artifact_ids:
        return frozenset()
    with request.app.state.session_factory() as session:
        rows = list(session.scalars(select(SqlArtifact).where(SqlArtifact.id.in_(artifact_ids))))
        by_id = {row.id: row for row in rows}
        snapshots = [
            (
                artifact_id,
                by_id[artifact_id].storage_key,
                ArtifactIntegrity(by_id[artifact_id].sha256, by_id[artifact_id].byte_length),
            )
            for artifact_id in artifact_ids
            if artifact_id in by_id and by_id[artifact_id].state is ArtifactState.COMMITTED
        ]
    if len(snapshots) != len(artifact_ids):
        raise HTTPException(409, "selected_artifact_unavailable")
    try:
        with artifact_storage(request) as store:
            for _, storage_key, integrity in snapshots:
                store.get_verified(storage_key, integrity)
    except ArtifactStorageError:
        raise HTTPException(503, "artifact_storage_unavailable") from None
    return frozenset(artifact_id for artifact_id, _, _ in snapshots)


@router.post(
    "/publication/preview",
    response_model=PublicationVersionPreview,
    operation_id="previewSelectivePublication",
)
def preview(
    payload: PublicationVersionSelection,
    request: Request,
    session: DbSession,
    actor: CurrentActor,
) -> PublicationVersionPreview:
    result = publication.preview(session, actor=actor, selection=payload.historical_selection())
    session.rollback()
    _verify_artifact_bytes(request, payload.artifact_ids)
    return PublicationVersionPreview.model_validate(
        version_envelope(result, publication_fields(session, result.public_fields))
    )


@router.post(
    "/publication/confirm",
    response_model=PublicationVersionManifestRead,
    status_code=201,
    operation_id="confirmSelectivePublication",
)
def confirm(
    payload: PublicationVersionConfirm,
    key: RetryKey,
    request: Request,
    session: DbSession,
    actor: CurrentActor,
) -> PublicationVersionManifestRead:
    selection = payload.historical_selection()
    current = publication.preview(session, actor=actor, selection=selection)
    if current.preview_digest != payload.preview_digest:
        session.rollback()
        raise DomainConflict("stale publication preview")
    session.rollback()
    verified = _verify_artifact_bytes(request, payload.artifact_ids)
    result = publication.confirm(
        session,
        actor=actor,
        payload=payload.historical_command(),
        key=key,
        verified_artifact_ids=verified,
    )
    return PublicationVersionManifestRead.model_validate(
        version_envelope(result, publication_fields(session, result.public_fields))
    )


@router.get(
    "/publication/history",
    response_model=PublicationVersionManifestPage,
    operation_id="listSelectivePublicationHistory",
)
def history(
    project_id: UUID,
    session: DbSession,
    actor: CurrentActor,
    limit: Limit = 25,
    cursor: Cursor = None,
) -> PublicationVersionManifestPage:
    result = publication.history(
        session,
        actor=actor,
        project_id=project_id,
        limit=limit,
        cursor=cursor,
    )
    return PublicationVersionManifestPage(
        items=[
            PublicationVersionManifestRead.model_validate(
                version_envelope(item, publication_fields(session, item.public_fields))
            )
            for item in result.items
        ],
        next_cursor=result.next_cursor,
    )


@router.get(
    "/publications/{manifest_id}",
    dependencies=[Depends(research_access)],
    response_model=PublicPublicationVersionManifestRead,
    operation_id="getPublicPublicationManifest",
)
def public_manifest(manifest_id: UUID, session: DbSession) -> PublicPublicationVersionManifestRead:
    result = publication.public_manifest(session, manifest_id)
    return PublicPublicationVersionManifestRead.model_validate(
        version_envelope(result, publication_fields(session, result.public_fields))
    )
