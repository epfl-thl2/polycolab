"""Anonymous access to exact artifact bytes released by publication."""

from uuid import UUID

from fastapi import HTTPException, Request, Response

from polycolab.app.dependencies import DbSession
from polycolab.artifacts import service as artifacts
from polycolab.artifacts.contracts import PublishedArtifactRead, public_download_headers
from polycolab.artifacts.routes.private import artifact_storage
from polycolab.artifacts.storage import ArtifactIntegrity, ArtifactStorageError
from polycolab.catalogue import publication
from polycolab.db.models import SqlArtifact


def _public_artifact(
    session: DbSession, artifact_id: UUID
) -> tuple[SqlArtifact, PublishedArtifactRead]:
    from polycolab.research.objects import ResearchNotFound

    try:
        return artifacts.public_artifact(session, artifact_id)
    except ResearchNotFound:
        return publication.public_artifact(session, artifact_id)


def metadata(artifact_id: UUID, session: DbSession) -> PublishedArtifactRead:
    _, projected = _public_artifact(session, artifact_id)
    return projected


def download(artifact_id: UUID, request: Request, session: DbSession) -> Response:
    artifact, _ = _public_artifact(session, artifact_id)
    storage_key = artifact.storage_key
    integrity = ArtifactIntegrity(artifact.sha256, artifact.byte_length)
    session.rollback()
    try:
        with artifact_storage(request) as store:
            data = store.get_verified(storage_key, integrity)
    except ArtifactStorageError:
        raise HTTPException(503, "artifact_storage_unavailable") from None
    # Moderation may withdraw the manifest while bytes are being read.
    with request.app.state.session_factory() as fresh:
        _public_artifact(fresh, artifact_id)
    return Response(content=data, headers=public_download_headers())
