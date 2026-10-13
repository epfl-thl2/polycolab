"""Shared evidence with stable-actor-private staging and exact attachments."""

import asyncio
from io import BytesIO
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from polycolab.access.actors import Actor
from polycolab.app.access import Access, ResearchAccess
from polycolab.app.cursors import Collection, Pagination
from polycolab.app.dependencies import DbSession
from polycolab.artifacts import service
from polycolab.artifacts.contracts import (
    ArtifactAttachmentItem,
    ArtifactAttachmentWrite,
    ArtifactRead,
    ArtifactUploadDeclaration,
    PublishedArtifactVersionRead,
    private_download_headers,
)
from polycolab.artifacts.routes import private, public
from polycolab.db.converters.artifacts import artifact as artifact_snapshot
from polycolab.db.models import (
    SqlArtifact,
    SqlArtifactResearchLink,
    SqlContributionEnvelope,
    SqlExternalAgentCredential,
    SqlHostedRunArtifact,
    SqlObjectRevision,
    SqlResearchActivityEvent,
    SqlResearchAttachment,
    SqlResearchScope,
    SqlUser,
)
from polycolab.entities.artifacts import ArtifactStorageError
from polycolab.entities.enums import ArtifactState
from polycolab.research.direct import (
    Destination,
    LibraryDestination,
    MutationResult,
    OutputRead,
    ProjectDestination,
    authorize,
    destination_scope,
    mutate,
)
from polycolab.research.history import visible_query
from polycolab.research.objects import ResearchNotFound
from polycolab.research.records import accessible_revision
from polycolab.research.routes.core import member, project
from polycolab.research.routes.direct import RetryKey

router = APIRouter(
    prefix="/api/v1", tags=["artifacts"], dependencies=[Depends(private.private_no_store)]
)


def artifact_scope(
    artifact_id: UUID, session: DbSession, access: Access
) -> tuple[SqlArtifact, SqlResearchScope, bool]:
    row = session.get(SqlArtifact, artifact_id)
    scope = session.get(SqlResearchScope, row.ownership_scope_id) if row else None
    if (
        row is None
        or scope is None
        or row.state not in {ArtifactState.STAGING, ArtifactState.COMMITTED}
    ):
        raise ResearchNotFound
    if session.get(SqlHostedRunArtifact, artifact_id) is not None:
        if access.user_id is None or access.credential is not None:
            raise ResearchNotFound
        service.read(
            session, project_id=scope.project_id, user_id=access.user_id, artifact_id=artifact_id
        )
        return row, scope, True
    if row.state == ArtifactState.STAGING:
        if access.user_id is None:
            raise ResearchNotFound
        authorize(session, access, scope)
        envelope = session.get(SqlContributionEnvelope, row.contribution_id)
        if envelope is None:
            raise ResearchNotFound
        if access.credential:
            if envelope.external_agent_id != access.credential.agent_id:
                raise ResearchNotFound
        elif envelope.human_user_id != access.user_id:
            raise ResearchNotFound
        service.read(
            session,
            project_id=scope.project_id,
            user_id=access.require_user_id(),
            artifact_id=row.id,
            include_staging=True,
        )
        return row, scope, True
    if scope.project_id and member(session, access, scope.project_id):
        if access.credential:
            # Recheck after storage I/O, including read-only memberships.
            from polycolab.agents.external import ExternalAgentInvalid, _aware
            from polycolab.entities.time import utc_now

            credential = session.get(
                SqlExternalAgentCredential, access.credential.id, populate_existing=True
            )
            if (
                credential is None
                or credential.revoked_at
                or _aware(credential.expires_at) <= utc_now()
            ):
                raise ExternalAgentInvalid
        project(session, access, scope.project_id)
        return row, scope, True
    public._public_artifact(session, artifact_id)
    return row, scope, False


def attachment_page(
    session: DbSession,
    access: Access,
    page: Pagination,
    project_id: UUID | None,
    revision_id: UUID | None,
) -> Collection[ArtifactAttachmentItem]:
    private_read = False
    if project_id:
        _, private_read = project(session, access, project_id)
    if revision_id:
        revision = session.get(SqlObjectRevision, revision_id)
        if revision is None or (project_id and revision.project_id != project_id):
            raise ResearchNotFound
        private_read = bool(revision.project_id and member(session, access, revision.project_id))
        if private_read:
            project(session, access, revision.project_id)
        else:
            accessible_revision(session, revision_id, None)
    query = (
        select(SqlArtifactResearchLink)
        .join(SqlArtifact, SqlArtifact.id == SqlArtifactResearchLink.artifact_id)
        .join(SqlObjectRevision, SqlObjectRevision.id == SqlArtifactResearchLink.revision_id)
        .where(SqlArtifact.state == ArtifactState.COMMITTED)
    )
    if project_id:
        query = query.where(SqlObjectRevision.project_id == project_id)
    if revision_id:
        query = query.where(SqlObjectRevision.id == revision_id)
    if not private_read:
        query = query.where(
            SqlArtifactResearchLink.id.in_(
                visible_query(access, "public")
                .where(SqlResearchActivityEvent.source_kind == "ArtifactResearchLink")
                .with_only_columns(SqlResearchActivityEvent.source_id)
            )
        )
    rows, cursor = page.select(
        session,
        query,
        SqlArtifactResearchLink.id,
        scope=f"attachments:{access.user_id}:{project_id}:{revision_id}",
    )
    items = []
    for link in rows:
        row = session.get(SqlArtifact, link.artifact_id)
        assert row
        items.append(
            ArtifactAttachmentItem(
                attachment_id=link.id,
                artifact=ArtifactRead.model_validate(row, from_attributes=True),
                source_object_version_id=row.source_revision_id if private_read else None,
                object_version_id=link.revision_id,
                attempt_object_version_id=link.attempt_revision_id,
                role=link.role,
                created_at=link.created_at,
            )
        )
    return Collection(items=items, next_cursor=cursor)


@router.get(
    "/projects/{project_id}/artifacts",
    response_model=Collection[ArtifactAttachmentItem],
    operation_id="pageArtifactAttachments",
)
def attachments(
    project_id: UUID,
    session: DbSession,
    access: Access,
    page: Pagination,
    object_version_id: UUID | None = None,
) -> Collection[ArtifactAttachmentItem]:
    return attachment_page(session, access, page, project_id, object_version_id)


@router.get(
    "/versions/{object_version_id}/attachments",
    response_model=Collection[ArtifactAttachmentItem],
    operation_id="listObjectVersionAttachments",
)
def object_version_attachments(
    object_version_id: UUID, session: DbSession, access: Access, page: Pagination
) -> Collection[ArtifactAttachmentItem]:
    return attachment_page(session, access, page, None, object_version_id)


def stage(
    request: Request,
    user_id: UUID,
    credential_id: UUID | None,
    destination: Destination,
    declaration: ArtifactUploadDeclaration,
    data: bytes,
    source_revision_id: UUID | None,
    retry_key: str,
) -> ArtifactRead:
    with request.app.state.session_factory() as session:
        access = (
            ResearchAccess(credential=session.get(SqlExternalAgentCredential, credential_id))
            if credential_id
            else ResearchAccess(user=session.get(SqlUser, user_id))
        )
        scope = destination_scope(session, destination)
        actor = authorize(session, access, scope)
        from polycolab.platform import mutation_keys
        from polycolab.projects.service import DomainConflict

        actor_key = (
            f"agent:{actor.external_agent_id}" if actor.external_agent_id else f"human:{user_id}"
        )
        payload = {
            "destination": destination.model_dump(mode="json"),
            "declaration": declaration.model_dump(mode="json"),
            "source_revision_id": str(source_revision_id) if source_revision_id else None,
        }
        if source_revision_id:
            accessible_revision(session, source_revision_id, scope.project_id)
        mutation_keys.lock_key(session, actor_key, "direct.artifact.stage", retry_key)
        receipt = mutation_keys.receipt(
            session, actor_key, "direct.artifact.stage", retry_key, payload
        )
        if receipt:
            saved = session.get(SqlArtifact, UUID(receipt.resource_ids[0]))
            if saved is None or saved.state not in {ArtifactState.STAGING, ArtifactState.COMMITTED}:
                raise ResearchNotFound
            from polycolab.agents.external import _aware
            from polycolab.entities.time import utc_now

            if saved.state == ArtifactState.STAGING and _aware(saved.expires_at) <= utc_now():
                raise DomainConflict("artifact staging expired")
            row = artifact_snapshot(saved)
            if saved.verified_at:
                return private._read(row)
        else:
            row = service.reserve(
                session,
                project_id=scope.project_id,
                user_id=user_id,
                declaration=declaration,
                settings=request.app.state.settings,
                source_revision_id=source_revision_id,
                actor=actor,
                library_destination_revision_id=destination.statement_revision_id
                if isinstance(destination, LibraryDestination)
                else None,
                commit=False,
            )
            mutation_keys.save(
                session, actor_key, "direct.artifact.stage", retry_key, payload, [row.id]
            )
        session.commit()

    try:
        with private.artifact_storage(request) as store:
            store.put_verified(row.storage_key, BytesIO(data), row.integrity)
    except ArtifactStorageError as error:
        code = str(error)
        raise HTTPException(
            422 if code in {"artifact_length_mismatch", "artifact_digest_mismatch"} else 503, code
        ) from None
    with request.app.state.session_factory() as session:
        access = (
            ResearchAccess(credential=session.get(SqlExternalAgentCredential, credential_id))
            if credential_id
            else ResearchAccess(user=session.get(SqlUser, user_id))
        )
        scope = destination_scope(session, destination)
        authorize(session, access, scope)
        return private._read(
            service.verified(
                session, project_id=scope.project_id, user_id=user_id, artifact_id=row.id
            )
        )


@router.post(
    "/artifacts",
    response_model=ArtifactRead,
    status_code=201,
    operation_id="uploadArtifact",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload(
    request: Request,
    session: DbSession,
    access: Access,
    sha256: Annotated[str, Query(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")],
    byte_length: Annotated[int, Query(ge=0, le=16 * 1024 * 1024)],
    project_id: UUID | None = None,
    statement_object_version_id: UUID | None = None,
    retry_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=200)
    ] = None,
    media_type: Annotated[
        str,
        Query(
            min_length=3, max_length=127, pattern=r"^[a-zA-Z0-9!#$&^_.+-]+/[a-zA-Z0-9!#$&^_.+-]+$"
        ),
    ] = "application/octet-stream",
    source_object_version_id: UUID | None = None,
) -> ArtifactRead:
    if (project_id is None) == (statement_object_version_id is None):
        raise HTTPException(422, "exactly_one_destination_required")
    destination = (
        ProjectDestination(kind="project", project_id=project_id)
        if project_id
        else LibraryDestination(
            kind="library", statement_revision_id=UUID(str(statement_object_version_id))
        )
    )
    scope = destination_scope(session, destination)
    authorize(session, access, scope)
    user_id = access.require_user_id()
    credential_id = access.credential.id if access.credential else None
    settings = request.app.state.settings
    if byte_length > settings.artifact_max_bytes:
        raise HTTPException(413, "artifact_size_limit")
    declaration = ArtifactUploadDeclaration(
        sha256=sha256, byte_length=byte_length, media_type=media_type
    )
    session.rollback()
    data = bytearray()
    try:
        async with asyncio.timeout(settings.artifact_request_timeout_seconds):
            async for chunk in request.stream():
                if len(data) + len(chunk) > byte_length:
                    raise HTTPException(413, "artifact_size_limit")
                data.extend(chunk)
    except TimeoutError:
        raise HTTPException(408, "artifact_upload_timeout") from None
    except ClientDisconnect:
        raise HTTPException(400, "artifact_upload_interrupted") from None
    if len(data) != byte_length:
        raise HTTPException(422, "artifact_length_mismatch")
    return await run_in_threadpool(
        stage,
        request,
        user_id,
        credential_id,
        destination,
        declaration,
        bytes(data),
        source_object_version_id,
        retry_key or str(uuid4()),
    )


@router.get(
    "/artifacts/{artifact_id}",
    response_model=ArtifactRead | PublishedArtifactVersionRead,
    operation_id="readArtifact",
)
def metadata(
    artifact_id: UUID, session: DbSession, access: Access
) -> ArtifactRead | PublishedArtifactVersionRead:
    row, _, private_read = artifact_scope(artifact_id, session, access)
    return (
        ArtifactRead.model_validate(row, from_attributes=True)
        if private_read
        else PublishedArtifactVersionRead.from_release(public.metadata(artifact_id, session))
    )


@router.get(
    "/artifacts/{artifact_id}/content", response_class=Response, operation_id="downloadArtifact"
)
def download(artifact_id: UUID, request: Request, session: DbSession, access: Access) -> Response:
    row, _, private_read = artifact_scope(artifact_id, session, access)
    if row.state != ArtifactState.COMMITTED:
        raise ResearchNotFound
    if not private_read:
        return public.download(artifact_id, request, session)
    stored = artifact_snapshot(row)
    session.rollback()
    try:
        with private.artifact_storage(request) as store:
            data = store.get_verified(stored.storage_key, stored.integrity)
    except ArtifactStorageError:
        raise HTTPException(503, "artifact_storage_unavailable") from None
    session.expire_all()
    artifact_scope(artifact_id, session, access)
    return Response(content=data, headers=private_download_headers())


class AttachmentCreate(ArtifactAttachmentWrite):
    artifact_id: UUID


@router.post("/attachments", response_model=MutationResult, operation_id="attachArtifact")
def attach(
    payload: AttachmentCreate, session: DbSession, access: Access, key: RetryKey
) -> MutationResult:
    row, scope, _ = artifact_scope(payload.artifact_id, session, access)
    target = accessible_revision(session, payload.object_version_id, scope.project_id)
    if target.ownership_scope_id != scope.id:
        raise ResearchNotFound
    if (
        row.library_destination_revision_id
        and target.id != row.library_destination_revision_id
        and not session.scalar(
            select(SqlResearchAttachment.revision_id).where(
                SqlResearchAttachment.revision_id == target.id,
                SqlResearchAttachment.statement_revision_id == row.library_destination_revision_id,
            )
        )
    ):
        raise HTTPException(403, "artifact_destination_mismatch")

    def apply(actor: Actor, envelope: SqlContributionEnvelope) -> list[OutputRead]:
        identity = service.attach(
            session,
            project_id=scope.project_id,
            user_id=access.require_user_id(),
            artifact_id=row.id,
            revision_id=payload.object_version_id,
            role=payload.role,
            attempt_revision_id=payload.attempt_object_version_id,
            actor=actor,
            contribution=envelope,
            commit=False,
        )
        return [OutputRead(entity_type="ARTIFACT_ATTACHMENT", entity_id=identity)]

    # Retain the stored retry encoding across the wire-contract rename.
    stored_payload = payload.model_dump(
        mode="json", exclude={"object_version_id", "attempt_object_version_id"}
    )
    stored_payload.update(
        revision_id=str(payload.object_version_id),
        attempt_revision_id=(
            str(payload.attempt_object_version_id) if payload.attempt_object_version_id else None
        ),
    )
    return mutate(session, access, scope, "artifact.attach", key, stored_payload, apply)
