"""Agent mutation controllers reused by the shared research resource routes."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import Header, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from polycolab.agents.external import (
    ExternalAgentUploadInterrupted,
    close_run,
    consume_mutation,
    run_actor,
)
from polycolab.agents.schemas import (
    ExternalCredentialRead,
    ExternalMutationRead,
    ExternalRunClose,
    ExternalRunDetail,
    ExternalRunOutputRead,
)
from polycolab.app.dependencies import DbSession
from polycolab.artifacts import service as artifacts
from polycolab.artifacts.contracts import (
    ArtifactAttachmentRead,
    ArtifactAttachmentWrite,
    ArtifactRead,
    ArtifactUploadDeclaration,
)
from polycolab.artifacts.routes.private import _read as artifact_read
from polycolab.artifacts.routes.private import _stage as stage_artifact
from polycolab.db.models import (
    SqlContributionEnvelope,
    SqlExternalAgentCredential,
    SqlExternalResearchRun,
    SqlExternalRunInvocation,
    SqlResearchObject,
)
from polycolab.entities.enums import CanonicalEntityType, ProvenanceKind, ResearchObjectKind
from polycolab.platform.outbox import canonical_digest
from polycolab.research.contributions import (
    ContributionMutation,
    ContributionOutput,
    record_contribution,
)
from polycolab.research.objects import (
    create_comment,
    create_object,
    create_relation,
    create_revision,
)
from polycolab.research.schemas import (
    CommentCreate,
    RelationCreate,
    ResearchObjectCreate,
    RevisionCreate,
)


def private_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


CurrentCredential = SqlExternalAgentCredential
RunStatus = Literal["OPEN", "COMPLETED", "FAILED", "REVOKED"]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _credential_read(row: SqlExternalAgentCredential) -> ExternalCredentialRead:
    return ExternalCredentialRead.model_validate(row)


def _run_read(session: DbSession, row: SqlExternalResearchRun) -> ExternalRunDetail:
    return ExternalRunDetail.model_validate(
        dict(
            id=row.id,
            credential_id=row.credential_id,
            project_id=row.project_id,
            sponsor_user_id=row.sponsor_user_id,
            client_request_id=row.client_request_id,
            title=row.title,
            input_revision_ids=[UUID(value) for value in row.input_revision_ids],
            outputs=[],
            status=cast(RunStatus, row.status),
            failure_code=row.failure_code,
            created_at=cast(datetime, _utc(row.created_at)),
            closed_at=_utc(row.closed_at),
        )
    )


def _credential_run(
    session: DbSession, credential: SqlExternalAgentCredential, run_id: UUID
) -> SqlExternalResearchRun:
    run, _actor, _sponsor = run_actor(session, credential=credential, run_id=run_id, mutation=False)
    return run


def post_close_run(
    run_id: UUID,
    payload: ExternalRunClose,
    idempotency_key: IdempotencyKey,
    session: DbSession,
    credential: CurrentCredential,
) -> ExternalRunDetail:
    request_payload = payload.model_dump(mode="json")
    _run, _actor, _sponsor = run_actor(
        session, credential=credential, run_id=run_id, mutation=False
    )
    existing = _invocation(
        session,
        run_id=run_id,
        operation="EXTERNAL_CLOSE_RUN",
        idempotency_key=idempotency_key,
        request_payload=request_payload,
    )
    if existing is not None:
        return _run_read(session, _credential_run(session, credential, run_id))
    row = close_run(
        session,
        credential=credential,
        run_id=run_id,
        status=payload.status,
        failure_code=payload.failure_code,
        commit=False,
    )
    session.add(
        SqlExternalRunInvocation(
            run_id=run_id,
            operation="EXTERNAL_CLOSE_RUN",
            idempotency_digest=canonical_digest(idempotency_key),
            request_digest=canonical_digest(request_payload),
            output_type="EXTERNAL_RUN",
            output_id=row.id,
        )
    )
    session.commit()
    return _run_read(session, row)


def _record_mutation(
    session: DbSession,
    *,
    credential: SqlExternalAgentCredential,
    run_id: UUID,
    operation: str,
    idempotency_key: str,
    request_payload: object,
    create_outputs: Callable[[SqlContributionEnvelope], list[ContributionOutput]],
) -> ExternalMutationRead:
    _run, actor, _sponsor = run_actor(session, credential=credential, run_id=run_id, mutation=False)
    existing = _invocation(
        session,
        run_id=run_id,
        operation=operation,
        idempotency_key=idempotency_key,
        request_payload=request_payload,
    )
    if existing is None:
        run_actor(session, credential=credential, run_id=run_id, mutation=True)
    mutation: ContributionMutation = record_contribution(
        session,
        actor=actor,
        operation=operation,
        idempotency_key=idempotency_key,
        request_payload=request_payload,
        create_outputs=create_outputs,
        ownership_scope_id=actor.ownership_scope_id,
        commit=False,
    )
    if not mutation.replayed:
        consume_mutation(session, credential_id=credential.id)
        primary = mutation.links[0]
        session.add(
            SqlExternalRunInvocation(
                run_id=run_id,
                operation=operation,
                idempotency_digest=canonical_digest(idempotency_key),
                request_digest=canonical_digest(request_payload),
                output_type=primary.canonical_entity_type.value,
                output_id=primary.canonical_entity_id,
            )
        )
    session.commit()
    return ExternalMutationRead(
        replayed=mutation.replayed,
        outputs=[
            ExternalRunOutputRead(
                entity_type=link.canonical_entity_type.value,
                entity_id=link.canonical_entity_id,
            )
            for link in mutation.links
        ],
    )


def _invocation(
    session: DbSession,
    *,
    run_id: UUID,
    operation: str,
    idempotency_key: str,
    request_payload: object,
) -> SqlExternalRunInvocation | None:
    row = session.scalar(
        select(SqlExternalRunInvocation).where(
            SqlExternalRunInvocation.run_id == run_id,
            SqlExternalRunInvocation.idempotency_digest == canonical_digest(idempotency_key),
        )
    )
    if row is not None and (
        row.operation != operation or row.request_digest != canonical_digest(request_payload)
    ):
        from polycolab.research.contributions import ContributionConflict

        raise ContributionConflict
    return row


def _scope_output(kind: CanonicalEntityType, entity_id: UUID, scope_id: UUID) -> ContributionOutput:
    return ContributionOutput(kind, entity_id, scope_id)


def post_object(
    run_id: UUID,
    payload: ResearchObjectCreate,
    idempotency_key: IdempotencyKey,
    session: DbSession,
    credential: CurrentCredential,
) -> ExternalMutationRead:
    if payload.kind not in {
        ResearchObjectKind.PROBLEM,
        ResearchObjectKind.CLAIM,
        ResearchObjectKind.ATTEMPT,
        ResearchObjectKind.PROOF_SKETCH,
    }:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unsupported_agent_object_kind")
    _run, actor, sponsor = run_actor(session, credential=credential, run_id=run_id, mutation=False)

    def create_outputs(envelope: SqlContributionEnvelope) -> list[ContributionOutput]:
        obj, revision = create_object(
            session,
            project_id=_run.project_id,
            kind=payload.kind,
            title=payload.title,
            content_md=payload.content_md,
            rationale=payload.rationale,
            proof=payload.proof_sketch,
            attempt=payload.attempt,
            author=sponsor,
            provenance_kind=ProvenanceKind.AGENT_DIRECT,
            actor=actor,
            contribution=envelope,
            commit=False,
        )
        assert actor.ownership_scope_id is not None
        return [
            _scope_output(CanonicalEntityType.RESEARCH_OBJECT, obj.id, actor.ownership_scope_id),
            _scope_output(
                CanonicalEntityType.OBJECT_REVISION, revision.id, actor.ownership_scope_id
            ),
        ]

    return _record_mutation(
        session,
        credential=credential,
        run_id=run_id,
        operation="EXTERNAL_CREATE_OBJECT",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        create_outputs=create_outputs,
    )


def post_revision(
    run_id: UUID,
    object_id: UUID,
    payload: RevisionCreate,
    idempotency_key: IdempotencyKey,
    session: DbSession,
    credential: CurrentCredential,
) -> ExternalMutationRead:
    _run, actor, sponsor = run_actor(session, credential=credential, run_id=run_id, mutation=False)
    obj = session.get(SqlResearchObject, object_id)
    if (
        obj is None
        or obj.project_id != _run.project_id
        or obj.kind
        not in {
            ResearchObjectKind.PROBLEM,
            ResearchObjectKind.CLAIM,
            ResearchObjectKind.ATTEMPT,
            ResearchObjectKind.PROOF_SKETCH,
        }
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")

    def create_outputs(envelope: SqlContributionEnvelope) -> list[ContributionOutput]:
        _obj, revision = create_revision(
            session,
            project_id=_run.project_id,
            object_id=object_id,
            base_revision_id=payload.base_revision_id,
            title=payload.title,
            content_md=payload.content_md,
            rationale=payload.rationale,
            proof=payload.proof_sketch,
            attempt=payload.attempt,
            author=sponsor,
            provenance_kind=ProvenanceKind.AGENT_DIRECT,
            actor=actor,
            contribution=envelope,
            commit=False,
        )
        assert actor.ownership_scope_id is not None
        return [
            _scope_output(
                CanonicalEntityType.OBJECT_REVISION, revision.id, actor.ownership_scope_id
            )
        ]

    return _record_mutation(
        session,
        credential=credential,
        run_id=run_id,
        operation="EXTERNAL_CREATE_REVISION",
        idempotency_key=idempotency_key,
        request_payload={"object_id": str(object_id), **payload.model_dump(mode="json")},
        create_outputs=create_outputs,
    )


def post_relation(
    run_id: UUID,
    payload: RelationCreate,
    idempotency_key: IdempotencyKey,
    session: DbSession,
    credential: CurrentCredential,
) -> ExternalMutationRead:
    _run, actor, sponsor = run_actor(session, credential=credential, run_id=run_id, mutation=False)

    def create_outputs(envelope: SqlContributionEnvelope) -> list[ContributionOutput]:
        relation = create_relation(
            session,
            project_id=_run.project_id,
            source_revision_id=payload.source_revision_id,
            target_revision_id=payload.target_revision_id,
            relation_type=payload.relation_type,
            rationale=payload.rationale,
            author=sponsor,
            provenance_kind=ProvenanceKind.AGENT_DIRECT,
            actor=actor,
            contribution=envelope,
            commit=False,
        )
        assert actor.ownership_scope_id is not None
        return [
            _scope_output(
                CanonicalEntityType.RELATION_ASSERTION, relation.id, actor.ownership_scope_id
            )
        ]

    return _record_mutation(
        session,
        credential=credential,
        run_id=run_id,
        operation="EXTERNAL_CREATE_RELATION",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        create_outputs=create_outputs,
    )


def post_comment(
    run_id: UUID,
    object_id: UUID,
    payload: CommentCreate,
    idempotency_key: IdempotencyKey,
    session: DbSession,
    credential: CurrentCredential,
) -> ExternalMutationRead:
    _run, actor, sponsor = run_actor(session, credential=credential, run_id=run_id, mutation=False)

    def create_outputs(envelope: SqlContributionEnvelope) -> list[ContributionOutput]:
        comment = create_comment(
            session,
            project_id=_run.project_id,
            object_id=object_id,
            revision_id=payload.revision_id,
            body_md=payload.body_md,
            author=sponsor,
            provenance_kind=ProvenanceKind.AGENT_DIRECT,
            actor=actor,
            contribution=envelope,
            commit=False,
        )
        assert actor.ownership_scope_id is not None
        return [
            _scope_output(
                CanonicalEntityType.RESEARCH_COMMENT, comment.id, actor.ownership_scope_id
            )
        ]

    return _record_mutation(
        session,
        credential=credential,
        run_id=run_id,
        operation="EXTERNAL_CREATE_COMMENT",
        idempotency_key=idempotency_key,
        request_payload={"object_id": str(object_id), **payload.model_dump(mode="json")},
        create_outputs=create_outputs,
    )


async def post_artifact(
    run_id: UUID,
    request: Request,
    idempotency_key: IdempotencyKey,
    session: DbSession,
    credential: CurrentCredential,
    sha256: Annotated[str, Query(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")],
    byte_length: Annotated[int, Query(ge=0, le=16 * 1024 * 1024)],
    media_type: Annotated[str, Query(max_length=127)] = "application/octet-stream",
    source_revision_id: UUID | None = None,
) -> ArtifactRead:
    settings = request.app.state.settings
    if byte_length > settings.artifact_max_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "artifact_size_limit")
    try:
        declaration = ArtifactUploadDeclaration(
            sha256=sha256, byte_length=byte_length, media_type=media_type
        )
    except ValidationError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "artifact_invalid_declaration"
        ) from None
    request_payload = {
        "sha256": sha256,
        "byte_length": byte_length,
        "media_type": media_type,
        "source_revision_id": str(source_revision_id) if source_revision_id else None,
    }
    _run, _actor, _sponsor = run_actor(
        session, credential=credential, run_id=run_id, mutation=False
    )
    existing = _invocation(
        session,
        run_id=run_id,
        operation="EXTERNAL_UPLOAD_ARTIFACT",
        idempotency_key=idempotency_key,
        request_payload=request_payload,
    )
    _run, actor, sponsor = run_actor(session, credential=credential, run_id=run_id, mutation=False)
    if existing is not None:
        return artifact_read(
            artifacts.read(
                session,
                project_id=_run.project_id,
                user_id=sponsor.id,
                artifact_id=existing.output_id,
                include_staging=True,
            )
        )
    run_actor(session, credential=credential, run_id=run_id, mutation=True)
    session.rollback()
    data = bytearray()
    try:
        async with asyncio.timeout(settings.artifact_request_timeout_seconds):
            async for chunk in request.stream():
                if len(data) + len(chunk) > byte_length:
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "artifact_size_limit"
                    )
                data.extend(chunk)
    except ClientDisconnect:
        raise ExternalAgentUploadInterrupted from None
    except TimeoutError:
        raise HTTPException(status.HTTP_408_REQUEST_TIMEOUT, "artifact_upload_timeout") from None
    if len(data) != byte_length:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "artifact_length_mismatch")
    uploaded = await run_in_threadpool(
        stage_artifact,
        request,
        _run.project_id,
        sponsor.id,
        declaration,
        bytes(data),
        source_revision_id,
        actor,
    )
    # Fence a credential or membership revoked while bytes were in transit. The
    # verified staging row remains private and is collected if this check fails.
    run_actor(session, credential=credential, run_id=run_id, mutation=True)
    consume_mutation(session, credential_id=credential.id)
    session.add(
        SqlExternalRunInvocation(
            run_id=run_id,
            operation="EXTERNAL_UPLOAD_ARTIFACT",
            idempotency_digest=canonical_digest(idempotency_key),
            request_digest=canonical_digest(request_payload),
            output_type="ARTIFACT",
            output_id=uploaded.id,
        )
    )
    session.commit()
    return uploaded


def post_artifact_attachment(
    run_id: UUID,
    artifact_id: UUID,
    payload: ArtifactAttachmentWrite,
    idempotency_key: IdempotencyKey,
    request: Request,
    session: DbSession,
    credential: CurrentCredential,
) -> ArtifactAttachmentRead:
    request_payload = {
        "artifact_id": str(artifact_id),
        **payload.model_dump(mode="json"),
    }
    # Existing external invocation records retain their original digest encoding.
    request_payload["revision_id"] = request_payload.pop("object_version_id")
    request_payload["attempt_revision_id"] = request_payload.pop("attempt_object_version_id")
    _run, _actor, _sponsor = run_actor(
        session, credential=credential, run_id=run_id, mutation=False
    )
    existing = _invocation(
        session,
        run_id=run_id,
        operation="EXTERNAL_ATTACH_ARTIFACT",
        idempotency_key=idempotency_key,
        request_payload=request_payload,
    )
    _run, actor, sponsor = run_actor(session, credential=credential, run_id=run_id, mutation=False)
    if existing is not None:
        return ArtifactAttachmentRead(id=existing.output_id)
    run_actor(session, credential=credential, run_id=run_id, mutation=True)
    attachment_id = artifacts.attach(
        session,
        project_id=_run.project_id,
        user_id=sponsor.id,
        artifact_id=artifact_id,
        revision_id=payload.object_version_id,
        role=payload.role,
        attempt_revision_id=payload.attempt_object_version_id,
        actor=actor,
        commit=False,
    )
    consume_mutation(session, credential_id=credential.id)
    session.add(
        SqlExternalRunInvocation(
            run_id=run_id,
            operation="EXTERNAL_ATTACH_ARTIFACT",
            idempotency_digest=canonical_digest(idempotency_key),
            request_digest=canonical_digest(request_payload),
            output_type="ARTIFACT_ATTACHMENT",
            output_id=attachment_id,
        )
    )
    session.commit()
    return ArtifactAttachmentRead(id=attachment_id)
