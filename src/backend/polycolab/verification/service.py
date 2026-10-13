"""API-owned verification lifecycle. No submitted source is executed here.

Lock order: retry receipt, project/membership, scope, capacity, job, attempt,
sorted artifacts. Candidate discovery is unlocked; every write rechecks under
locks. Byte I/O is performed by the service adapter between database phases.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from polycolab.access.authorization import (
    AuthorizationDenied,
    ProjectAction,
    ProjectNotFound,
    lock_project_authorization,
    project_policy,
)
from polycolab.artifacts.service import StoredArtifact
from polycolab.artifacts.storage import ArtifactIntegrity, new_staging_key
from polycolab.catalogue.publication import public_artifact
from polycolab.db.converters.artifacts import artifact as stored_artifact
from polycolab.db.models import (
    SqlArtifact,
    SqlContributionEnvelope,
    SqlObjectRevision,
    SqlRecordRevision,
    SqlResearchAttemptRevision,
    SqlResearchScope,
    SqlRunArtifactOutput,
    SqlVerificationAttempt,
    SqlVerificationEnvironment,
    SqlVerificationEvent,
    SqlVerificationInput,
    SqlVerificationJob,
    SqlVerificationOutputArtifact,
    SqlVerificationReservation,
    SqlVerificationResult,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import (
    ArtifactState,
    VerificationAttemptState,
    VerificationInputRole,
    VerificationJobState,
    VerificationOutputRole,
    VerificationReservationState,
)
from polycolab.entities.time import utc_now
from polycolab.platform import mutation_keys
from polycolab.platform.config import Settings
from polycolab.platform.outbox import append_event, canonical_digest
from polycolab.projects.service import DomainConflict
from polycolab.research.contributions import human_contribution
from polycolab.research.objects import ResearchNotFound
from polycolab.research.records import accessible_revision
from polycolab.verification import limits as execution_limits
from polycolab.verification.contracts import (
    AttemptBinding,
    AttemptRead,
    ControllerClaim,
    ControllerCompletion,
    EventRead,
    InputReference,
    JobPurpose,
    JobRead,
    JobSubmission,
    OutputReference,
    OutputStageRequest,
    ResourceLimits,
    ResultRead,
    request_digest,
    validate_completion_limits,
)
from polycolab.verification.queue import candidate_page

LIVE = (VerificationJobState.QUEUED, VerificationJobState.RUNNING)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


@contextmanager
def transaction(session: Session) -> Iterator[None]:
    try:
        yield
        session.commit()
    except Exception:
        session.rollback()
        raise


def _scope(session: Session, project_id: UUID, user_id: UUID, *, write: bool) -> SqlResearchScope:
    lock_project_authorization(
        SqlAlchemyTransaction(session), project_id=project_id, user_id=user_id
    )
    project_policy.require_scope(
        SqlAlchemyTransaction(session),
        project_id,
        user_id,
        ProjectAction.CREATE_RESEARCH if write else ProjectAction.VIEW,
    )
    scope = session.scalar(
        select(SqlResearchScope).where(SqlResearchScope.project_id == project_id).with_for_update()
    )
    if scope is None:
        raise ResearchNotFound
    return scope


def _limits(job: SqlVerificationJob) -> ResourceLimits:
    return ResourceLimits.model_validate(
        {name: getattr(job, name) for name in ResourceLimits.model_fields}
    )


def _inputs(session: Session, job_id: UUID) -> list[SqlVerificationInput]:
    return list(
        session.scalars(
            select(SqlVerificationInput)
            .where(SqlVerificationInput.job_id == job_id)
            .order_by(SqlVerificationInput.position)
        )
    )


def _submission(session: Session, job: SqlVerificationJob, project_id: UUID) -> JobSubmission:
    return JobSubmission(
        project_id=project_id,
        work_target_revision_id=job.work_target_revision_id,
        research_attempt_revision_id=job.research_attempt_revision_id,
        environment_id=job.environment_id,
        purpose=JobPurpose(job.purpose),
        evidence_scope=job.evidence_scope,
        entrypoint=job.entrypoint,
        arguments=tuple(job.arguments),
        seed=job.seed,
        limits=_limits(job),
        inputs=tuple(
            InputReference.model_validate(
                {
                    "path": row.path,
                    "role": row.role.value,
                    "revision_id": row.revision_id,
                    "artifact_id": row.artifact_id,
                }
            )
            for row in _inputs(session, job.id)
        ),
    )


def _input_identity(
    session: Session, reference: InputReference, project_id: UUID, scope_id: UUID
) -> tuple[str, int]:
    if reference.revision_id is not None:
        row = accessible_revision(session, reference.revision_id, project_id)
        content = row.content_md.encode("utf-8")
        return hashlib.sha256(content).hexdigest(), len(content)
    artifact = session.get(SqlArtifact, reference.artifact_id)
    if artifact is None or artifact.state != ArtifactState.COMMITTED:
        raise ResearchNotFound
    if artifact.ownership_scope_id != scope_id:
        public_artifact(session, artifact.id)
    return artifact.sha256, artifact.byte_length


def _authorize_inputs(session: Session, submission: JobSubmission, scope_id: UUID) -> list[str]:
    target = accessible_revision(session, submission.work_target_revision_id, submission.project_id)
    if target.ownership_scope_id != scope_id:
        raise ResearchNotFound
    if submission.research_attempt_revision_id is not None:
        attempt = session.get(SqlResearchAttemptRevision, submission.research_attempt_revision_id)
        revision = accessible_revision(
            session, submission.research_attempt_revision_id, submission.project_id
        )
        if (
            attempt is None
            or attempt.target_revision_id != target.id
            or revision.ownership_scope_id != scope_id
        ):
            raise ResearchNotFound
    identities = [
        _input_identity(session, item, submission.project_id, scope_id)
        for item in submission.inputs
    ]
    expected_source_kind = (
        "FORMALIZATION" if submission.purpose == JobPurpose.LEAN_CHECK else "COMPUTATION"
    )
    for item in submission.inputs:
        if item.role != "SOURCE":
            continue
        source = session.get(SqlRecordRevision, item.revision_id) if item.revision_id else None
        version = session.get(SqlObjectRevision, item.revision_id) if item.revision_id else None
        language = version.semantic_metadata.get("source_language") if version else None
        expected_language = "LEAN" if submission.purpose == JobPurpose.LEAN_CHECK else "PYTHON"
        if source is None or (
            source.kind != expected_source_kind and language != expected_language
        ):
            raise DomainConflict("verification_source_kind_mismatch")
    if sum(size for _, size in identities) > submission.limits.disk_bytes:
        raise DomainConflict("verification_inputs_exceed_disk")
    return [digest for digest, _ in identities]


def _event(
    session: Session,
    job: SqlVerificationJob,
    name: str,
    attempt: SqlVerificationAttempt | None = None,
) -> None:
    job.event_sequence += 1
    session.add(
        SqlVerificationEvent(
            job_id=job.id,
            sequence=job.event_sequence,
            attempt_id=attempt.id if attempt else None,
            event_type=name,
            payload={},
        )
    )
    append_event(
        session,
        event_type=f"verification.{name.lower()}",
        aggregate_type="verification_job",
        aggregate_id=job.id,
        ownership_scope_id=job.ownership_scope_id,
        payload={"job_id": str(job.id), "sequence": job.event_sequence},
    )


def _snapshot(session: Session, job: SqlVerificationJob, project_id: UUID) -> JobRead:
    attempts = list(
        session.scalars(
            select(SqlVerificationAttempt)
            .where(SqlVerificationAttempt.job_id == job.id)
            .order_by(SqlVerificationAttempt.generation)
        )
    )
    results = []
    for result in session.scalars(
        select(SqlVerificationResult)
        .where(SqlVerificationResult.job_id == job.id)
        .order_by(SqlVerificationResult.created_at, SqlVerificationResult.id)
    ):
        outputs = tuple(
            OutputReference.model_validate(
                {
                    "artifact_id": artifact.id,
                    "path": binding.path,
                    "sha256": artifact.sha256,
                    "byte_length": artifact.byte_length,
                    "role": binding.role.value,
                }
            )
            for binding, artifact in session.execute(
                select(SqlVerificationOutputArtifact, SqlArtifact)
                .join(SqlArtifact, SqlArtifact.id == SqlVerificationOutputArtifact.artifact_id)
                .where(SqlVerificationOutputArtifact.result_id == result.id)
                .order_by(SqlVerificationOutputArtifact.path)
            )
        )
        results.append(
            ResultRead(
                id=result.id,
                attempt_id=result.attempt_id,
                outcome=result.outcome,
                diagnostic_summary=result.diagnostic_summary,
                created_at=utc(result.created_at),
                outputs=outputs,
            )
        )
    return JobRead(
        id=job.id,
        submission=_submission(session, job, project_id),
        manifest_digest=job.manifest_digest,
        state=job.state.value,
        generation=job.current_generation,
        event_sequence=job.event_sequence,
        deadline_at=utc(job.deadline_at),
        terminal_reason=job.terminal_reason,
        attempts=tuple(
            AttemptRead(
                id=a.id,
                generation=a.generation,
                state=a.state.value,
                started_at=utc(a.started_at),
                terminal_at=utc(a.terminal_at) if a.terminal_at else None,
            )
            for a in attempts
        ),
        results=tuple(results),
    )


def submit(
    session: Session,
    *,
    user_id: UUID,
    submission: JobSubmission,
    retry_key: str,
    settings: Settings,
    agent_token: str | None = None,
    source_event_cursor: int | None = None,
) -> JobRead:
    if not settings.feature_verification_submission_enabled:
        raise ResearchNotFound
    with transaction(session):
        mutation_keys.lock_key(
            session, f"verification:{user_id}:{submission.project_id}", "submit", retry_key
        )
        scope = _scope(session, submission.project_id, user_id, write=True)
        authority = None
        if agent_token is not None:
            from polycolab.verification.tools import authorize

            authority = authorize(
                session,
                token=agent_token,
                name="submit_verification",
                user_id=user_id,
                project_id=submission.project_id,
            )
            authority.check_submission(submission)
            source_event_cursor = authority.verify_invocation(
                session,
                retry_key,
                source_event_cursor,
                tool_name="submit_verification",
            )
        retry_digest = canonical_digest([authority.run.id if authority else "human", retry_key])
        digests = _authorize_inputs(session, submission, scope.id)
        existing = session.scalar(
            select(SqlVerificationJob).where(
                SqlVerificationJob.sponsor_user_id == user_id,
                SqlVerificationJob.ownership_scope_id == scope.id,
                SqlVerificationJob.retry_key_digest == retry_digest,
            )
        )
        if existing is not None:
            if existing.request_digest != request_digest(submission):
                raise DomainConflict("verification_retry_mismatch")
            if authority:
                authority.fence(session)
            return _snapshot(session, existing, submission.project_id)
        environment = session.get(SqlVerificationEnvironment, submission.environment_id)
        language = "LEAN" if submission.purpose == JobPurpose.LEAN_CHECK else "PYTHON"
        if (
            environment is None
            or not environment.available
            or environment.language.value != language
        ):
            raise DomainConflict("verification_environment_unavailable")
        if (
            len(submission.inputs) > settings.verification_manifest_max_inputs
            or any(
                value > getattr(environment, f"max_{name}")
                for name, value in submission.limits.model_dump().items()
            )
            or submission.limits.wall_seconds > settings.verification_deadline_seconds
        ):
            raise DomainConflict("verification_limits_exceeded")
        execution_limits.lock_capacity(session)
        execution_limits.admit(
            session, user_id=user_id, scope_id=scope.id, limits=submission.limits, settings=settings
        )
        if authority:
            assert source_event_cursor is not None
            contribution = authority.contribution(
                session, scope.id, source_cursor=source_event_cursor
            )
        else:
            contribution = human_contribution(
                session, user_id=user_id, scope_id=scope.id, operation="verification.submit"
            )
        job = SqlVerificationJob(
            ownership_scope_id=scope.id,
            sponsor_user_id=user_id,
            contribution_id=contribution.id,
            work_target_revision_id=submission.work_target_revision_id,
            research_attempt_revision_id=submission.research_attempt_revision_id,
            environment_id=submission.environment_id,
            purpose=submission.purpose.value,
            evidence_scope=submission.evidence_scope,
            entrypoint=submission.entrypoint,
            arguments=list(submission.arguments),
            seed=submission.seed,
            manifest_digest=canonical_digest(
                [
                    {"input": item.model_dump(mode="json"), "sha256": digest}
                    for item, digest in zip(submission.inputs, digests, strict=True)
                ]
            ),
            request_digest=request_digest(submission),
            retry_key_digest=retry_digest,
            contract_version=1,
            **submission.limits.model_dump(),
            max_attempts=settings.verification_max_attempts,
            deadline_at=utc_now() + timedelta(seconds=settings.verification_deadline_seconds),
        )
        session.add(job)
        session.flush()
        for position, (item, digest) in enumerate(zip(submission.inputs, digests, strict=True)):
            session.add(
                SqlVerificationInput(
                    job_id=job.id,
                    position=position,
                    path=item.path,
                    role=VerificationInputRole(item.role),
                    revision_id=item.revision_id,
                    artifact_id=item.artifact_id,
                    sha256=digest,
                )
            )
        session.add(
            SqlVerificationReservation(
                job_id=job.id,
                sponsor_user_id=user_id,
                ownership_scope_id=scope.id,
                cpu_seconds=job.cpu_seconds * job.max_attempts,
                memory_byte_seconds=job.memory_bytes * job.wall_seconds * job.max_attempts,
                disk_bytes=job.disk_bytes,
                output_bytes=job.output_bytes + job.log_bytes,
            )
        )
        if authority:
            authority.fence(session)
        _event(session, job, "ADMITTED")
        return _snapshot(session, job, submission.project_id)


def _job(
    session: Session, job_id: UUID, scope_id: UUID, *, skip_locked: bool = False
) -> SqlVerificationJob:
    row = session.scalar(
        select(SqlVerificationJob)
        .where(SqlVerificationJob.id == job_id, SqlVerificationJob.ownership_scope_id == scope_id)
        .with_for_update(skip_locked=skip_locked)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise ResearchNotFound
    return row


def inspect(
    session: Session,
    *,
    job_id: UUID,
    project_id: UUID,
    user_id: UUID,
    agent_token: str | None = None,
) -> JobRead:
    with transaction(session):
        scope = _scope(session, project_id, user_id, write=False)
        authority = None
        if agent_token is not None:
            from polycolab.verification.tools import authorize

            authority = authorize(
                session,
                token=agent_token,
                name="inspect_verification",
                user_id=user_id,
                project_id=project_id,
            )
        job = _job(session, job_id, scope.id)
        if authority:
            envelope = session.get(SqlContributionEnvelope, job.contribution_id)
            if envelope is None or envelope.run_id != authority.run.id:
                raise ResearchNotFound
            authority.check_submission(_submission(session, job, project_id))
            authority.fence(session)
        _authorize_inputs(session, _submission(session, job, project_id), scope.id)
        return _snapshot(session, job, project_id)


def events(
    session: Session,
    *,
    job_id: UUID,
    project_id: UUID,
    user_id: UUID,
    after: int,
    limit: int,
    settings: Settings,
) -> tuple[EventRead, ...]:
    if after < 0 or not 1 <= limit <= settings.verification_event_page_size:
        raise DomainConflict("invalid_event_page")
    with transaction(session):
        scope = _scope(session, project_id, user_id, write=False)
        job = _job(session, job_id, scope.id)
        _authorize_inputs(session, _submission(session, job, project_id), scope.id)
        return tuple(
            EventRead(
                sequence=e.sequence,
                attempt_id=e.attempt_id,
                event_type=e.event_type,
                created_at=utc(e.created_at),
            )
            for e in session.scalars(
                select(SqlVerificationEvent)
                .where(SqlVerificationEvent.job_id == job.id, SqlVerificationEvent.sequence > after)
                .order_by(SqlVerificationEvent.sequence)
                .limit(limit)
            )
        )


def _attempt(session: Session, job: SqlVerificationJob) -> SqlVerificationAttempt | None:
    return session.scalar(
        select(SqlVerificationAttempt)
        .where(
            SqlVerificationAttempt.job_id == job.id,
            SqlVerificationAttempt.generation == job.current_generation,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _finish(
    session: Session,
    job: SqlVerificationJob,
    state: VerificationJobState,
    reason: str,
    attempt: SqlVerificationAttempt | None,
    *,
    acknowledged: bool = False,
) -> None:
    now = utc_now()
    # Flush the event together with the terminal transition; terminal rows are
    # immutable in PostgreSQL and cannot receive a second UPDATE.
    if attempt is not None and attempt.state == VerificationAttemptState.ACTIVE:
        attempt.state = VerificationAttemptState(state.value)
        attempt.terminal_at = now
    reservation = session.get(SqlVerificationReservation, job.id)
    assert reservation is not None
    reservation.state = VerificationReservationState.RELEASED
    reservation.released_at = now
    reservation.accounted_at = (
        max(now, utc(attempt.started_at) + timedelta(seconds=job.wall_seconds))
        if attempt and not acknowledged
        else now
    )
    job.state = state
    job.terminal_at = now
    job.terminal_reason = reason
    _event(session, job, state.value, attempt)


def cancel(
    session: Session,
    *,
    job_id: UUID,
    project_id: UUID,
    user_id: UUID,
    agent_token: str | None = None,
    invocation_key: str | None = None,
    source_event_cursor: int | None = None,
) -> JobRead:
    with transaction(session):
        scope = _scope(session, project_id, user_id, write=True)
        authority = None
        if agent_token is not None:
            from polycolab.verification.tools import authorize

            authority = authorize(
                session,
                token=agent_token,
                name="cancel_verification",
                user_id=user_id,
                project_id=project_id,
            )
            if invocation_key is None:
                raise AuthorizationDenied("missing verification invocation provenance")
            authority.verify_invocation(
                session,
                invocation_key,
                source_event_cursor,
                tool_name="cancel_verification",
            )
        execution_limits.lock_capacity(session)
        job = _job(session, job_id, scope.id)
        if authority:
            envelope = session.get(SqlContributionEnvelope, job.contribution_id)
            if envelope is None or envelope.run_id != authority.run.id:
                raise ResearchNotFound
            authority.check_submission(_submission(session, job, project_id))
            authority.fence(session)
        if job.state in LIVE:
            _finish(
                session,
                job,
                VerificationJobState.CANCELLED,
                "USER_CANCELLED",
                _attempt(session, job),
            )
        return _snapshot(session, job, project_id)


def rerun(
    session: Session,
    *,
    job_id: UUID,
    project_id: UUID,
    user_id: UUID,
    retry_key: str,
    settings: Settings,
) -> JobRead:
    original = inspect(session, job_id=job_id, project_id=project_id, user_id=user_id)
    return submit(
        session,
        user_id=user_id,
        submission=original.submission,
        retry_key=retry_key,
        settings=settings,
    )


def _controller_context(
    session: Session, job_id: UUID, *, authorize: bool = True
) -> tuple[SqlVerificationJob, UUID]:
    candidate = session.get(SqlVerificationJob, job_id)
    scope = session.get(SqlResearchScope, candidate.ownership_scope_id) if candidate else None
    if candidate is None or scope is None or scope.project_id is None:
        raise ResearchNotFound
    lock_project_authorization(
        SqlAlchemyTransaction(session),
        project_id=scope.project_id,
        user_id=candidate.sponsor_user_id,
    )
    session.scalar(
        select(SqlResearchScope).where(SqlResearchScope.id == scope.id).with_for_update()
    )
    execution_limits.lock_capacity(session)
    job = _job(session, job_id, scope.id, skip_locked=True)
    if authorize:
        _authorize_job(session, job, scope.project_id)
    return job, scope.project_id


def _authorize_job(session: Session, job: SqlVerificationJob, project_id: UUID) -> None:
    project_policy.require_scope(
        SqlAlchemyTransaction(session),
        project_id,
        job.sponsor_user_id,
        ProjectAction.CREATE_RESEARCH,
    )
    _authorize_inputs(session, _submission(session, job, project_id), job.ownership_scope_id)


def _fence(
    session: Session, job: SqlVerificationJob, binding: AttemptBinding, controller_id: str
) -> SqlVerificationAttempt:
    attempt = _attempt(session, job)
    if (
        job.state != VerificationJobState.RUNNING
        or attempt is None
        or attempt.id != binding.attempt_id
        or attempt.generation != binding.generation
        or attempt.controller_id != controller_id
        or attempt.state != VerificationAttemptState.ACTIVE
        or utc(attempt.lease_expires_at) <= utc_now()
        or utc(job.deadline_at) <= utc_now()
        or utc(attempt.started_at) + timedelta(seconds=job.wall_seconds) <= utc_now()
    ):
        raise DomainConflict("verification_stale_attempt")
    return attempt


def _claim_read(
    session: Session, job: SqlVerificationJob, attempt: SqlVerificationAttempt, project_id: UUID
) -> ControllerClaim:
    environment = session.get(SqlVerificationEnvironment, job.environment_id)
    assert environment is not None
    return ControllerClaim(
        job_id=job.id,
        attempt_id=attempt.id,
        generation=attempt.generation,
        lease_expires_at=utc(attempt.lease_expires_at),
        execution_deadline_at=min(
            utc(job.deadline_at), utc(attempt.started_at) + timedelta(seconds=job.wall_seconds)
        ),
        submission=_submission(session, job, project_id),
        manifest_digest=job.manifest_digest,
        image_digest=environment.image_digest,
        toolchain_version=environment.toolchain_version,
        dependency_lock_digest=environment.dependency_lock_digest,
        build_digest=environment.build_digest,
        platform_identity=environment.platform_identity,
    )


def claim(session: Session, *, controller_id: str, settings: Settings) -> ControllerClaim | None:
    # Configuration at the API boundary is independently gated. Domain tests may
    # exercise this state machine without a runnable execution service.
    ids = candidate_page(session)
    session.rollback()
    for job_id in ids:
        try:
            with transaction(session):
                job, project_id = _controller_context(session, job_id, authorize=False)
                if job.state != VerificationJobState.QUEUED:
                    continue
                previous = _attempt(session, job)
                try:
                    _authorize_job(session, job, project_id)
                except ResearchNotFound, AuthorizationDenied, ProjectNotFound:
                    _finish(
                        session, job, VerificationJobState.FAILED, "AUTHORITY_REVOKED", previous
                    )
                    continue
                if (
                    previous
                    and utc(previous.started_at) + timedelta(seconds=job.wall_seconds) > utc_now()
                ):
                    continue
                if utc(job.deadline_at) <= utc_now():
                    _finish(session, job, VerificationJobState.TIMED_OUT, "DEADLINE", previous)
                    continue
                env = session.get(SqlVerificationEnvironment, job.environment_id)
                if env is None or not env.available:
                    _finish(
                        session,
                        job,
                        VerificationJobState.FAILED,
                        "ENVIRONMENT_UNAVAILABLE",
                        previous,
                    )
                    continue
                if job.current_generation >= job.max_attempts:
                    _finish(
                        session, job, VerificationJobState.FAILED, "ATTEMPTS_EXHAUSTED", previous
                    )
                    continue
                job.current_generation += 1
                attempt = SqlVerificationAttempt(
                    started_at=utc_now(),
                    job_id=job.id,
                    generation=job.current_generation,
                    controller_id=controller_id,
                    lease_expires_at=min(
                        utc(job.deadline_at),
                        utc_now()
                        + timedelta(
                            seconds=min(settings.verification_lease_seconds, job.wall_seconds)
                        ),
                    ),
                )
                session.add(attempt)
                session.flush()
                job.state = VerificationJobState.RUNNING
                _event(session, job, "CLAIMED", attempt)
                return _claim_read(session, job, attempt, project_id)
        except ResearchNotFound, AuthorizationDenied, ProjectNotFound:
            continue
    return None


def renew(
    session: Session, *, binding: AttemptBinding, controller_id: str, settings: Settings
) -> ControllerClaim:
    with transaction(session):
        job, project_id = _controller_context(session, binding.job_id)
        attempt = _fence(session, job, binding, controller_id)
        attempt.lease_expires_at = min(
            utc(job.deadline_at),
            utc(attempt.started_at) + timedelta(seconds=job.wall_seconds),
            utc_now() + timedelta(seconds=settings.verification_lease_seconds),
        )
        return _claim_read(session, job, attempt, project_id)


def recover(session: Session, *, limit: int = 100) -> int:
    if not 1 <= limit <= 100:
        raise ValueError("invalid recovery page")
    ids = list(
        session.scalars(
            select(SqlVerificationJob.id)
            .where(
                SqlVerificationJob.state.in_(LIVE),
                or_(
                    SqlVerificationJob.deadline_at <= utc_now(),
                    SqlVerificationJob.id.in_(
                        select(SqlVerificationAttempt.job_id).where(
                            SqlVerificationAttempt.state == VerificationAttemptState.ACTIVE,
                            SqlVerificationAttempt.lease_expires_at <= utc_now(),
                        )
                    ),
                ),
            )
            .order_by(SqlVerificationJob.deadline_at, SqlVerificationJob.id)
            .limit(limit)
        )
    )
    session.rollback()
    changed = 0
    for job_id in ids:
        with transaction(session):
            candidate = session.get(SqlVerificationJob, job_id)
            assert candidate is not None
            scope = session.get(SqlResearchScope, candidate.ownership_scope_id)
            assert scope is not None and scope.project_id is not None
            lock_project_authorization(
                SqlAlchemyTransaction(session),
                project_id=scope.project_id,
                user_id=candidate.sponsor_user_id,
            )
            session.scalar(
                select(SqlResearchScope).where(SqlResearchScope.id == scope.id).with_for_update()
            )
            execution_limits.lock_capacity(session)
            job = _job(session, job_id, scope.id)
            if job.state not in LIVE:
                continue
            attempt = _attempt(session, job)
            reason = None
            try:
                _authorize_job(session, job, scope.project_id)
            except ResearchNotFound, AuthorizationDenied, ProjectNotFound:
                reason = "AUTHORITY_REVOKED"
            if reason or utc(job.deadline_at) <= utc_now():
                _finish(
                    session,
                    job,
                    VerificationJobState.FAILED if reason else VerificationJobState.TIMED_OUT,
                    reason or "DEADLINE",
                    attempt,
                )
                changed += 1
            elif (
                attempt
                and attempt.state == VerificationAttemptState.ACTIVE
                and utc(attempt.lease_expires_at) <= utc_now()
            ):
                attempt.state = VerificationAttemptState.LEASE_LOST
                attempt.terminal_at = utc_now()
                session.add(
                    SqlVerificationResult(
                        job_id=job.id,
                        attempt_id=attempt.id,
                        environment_id=job.environment_id,
                        input_manifest_digest=job.manifest_digest,
                        outcome="FAILED",
                        diagnostic_summary={"code": "LEASE_LOST"},
                        usage_summary={},
                        completion_request_digest=canonical_digest(["lease_lost", attempt.id]),
                    )
                )
                if job.current_generation >= job.max_attempts:
                    _finish(
                        session, job, VerificationJobState.FAILED, "ATTEMPTS_EXHAUSTED", attempt
                    )
                else:
                    job.state = VerificationJobState.QUEUED
                    _event(session, job, "LEASE_LOST", attempt)
                changed += 1
    return changed


@dataclass(frozen=True)
class InputBytes:
    sha256: str
    data: bytes | None
    artifact: StoredArtifact | None


def input_bytes(
    session: Session, *, binding: AttemptBinding, controller_id: str, position: int
) -> InputBytes:
    with transaction(session):
        job, project_id = _controller_context(session, binding.job_id)
        _fence(session, job, binding, controller_id)
        row = session.get(SqlVerificationInput, (job.id, position))
        if row is None:
            raise ResearchNotFound
        if row.revision_id is not None:
            data = accessible_revision(session, row.revision_id, project_id).content_md.encode(
                "utf-8"
            )
            if hashlib.sha256(data).hexdigest() != row.sha256:
                raise DomainConflict("verification_input_integrity")
            return InputBytes(row.sha256, data, None)
        artifact = session.get(SqlArtifact, row.artifact_id)
        assert artifact is not None
        return InputBytes(row.sha256, None, stored_artifact(artifact))


def stage(
    session: Session, *, payload: OutputStageRequest, controller_id: str, settings: Settings
) -> StoredArtifact:
    with transaction(session):
        job, _ = _controller_context(session, payload.job_id)
        attempt = _fence(session, job, payload, controller_id)
        rows = list(
            session.execute(
                select(SqlVerificationOutputArtifact, SqlArtifact)
                .join(SqlArtifact, SqlArtifact.id == SqlVerificationOutputArtifact.artifact_id)
                .where(SqlVerificationOutputArtifact.attempt_id == attempt.id)
            )
        )
        for binding, artifact in rows:
            if binding.path == payload.path:
                if (
                    binding.role.value != payload.role
                    or artifact.sha256 != payload.sha256
                    or artifact.byte_length != payload.byte_length
                ):
                    raise DomainConflict("verification_output_retry_mismatch")
                if artifact.state != ArtifactState.STAGING or utc(artifact.expires_at) <= utc_now():
                    raise DomainConflict("verification_output_expired")
                return stored_artifact(artifact)
        declarations = [
            OutputReference.model_validate(
                {
                    "artifact_id": a.id,
                    "path": b.path,
                    "role": b.role.value,
                    "sha256": a.sha256,
                    "byte_length": a.byte_length,
                }
            )
            for b, a in rows
        ]
        from uuid import uuid4

        declaration = OutputReference.model_validate(
            {
                "artifact_id": uuid4(),
                "path": payload.path,
                "role": payload.role,
                "sha256": payload.sha256,
                "byte_length": payload.byte_length,
            }
        )
        completion = ControllerCompletion(
            job_id=job.id,
            attempt_id=attempt.id,
            generation=attempt.generation,
            outcome="COMPLETED",
            exit_code=0,
            diagnostic_code="NONE",
            outputs=tuple([*declarations, declaration]),
        )
        validate_completion_limits(completion, _limits(job))
        if payload.byte_length > settings.artifact_max_bytes:
            raise DomainConflict("verification_output_too_large")
        artifact = SqlArtifact(
            id=declaration.artifact_id,
            ownership_scope_id=job.ownership_scope_id,
            contribution_id=job.contribution_id,
            created_by_user_id=job.sponsor_user_id,
            sha256=payload.sha256,
            byte_length=payload.byte_length,
            media_type="application/octet-stream",
            storage_key=new_staging_key(),
            source_revision_id=job.work_target_revision_id,
            state=ArtifactState.STAGING,
            expires_at=max(utc(job.deadline_at), utc_now())
            + timedelta(seconds=settings.artifact_staging_ttl_seconds),
        )
        session.add(artifact)
        session.flush()
        session.add(
            SqlVerificationOutputArtifact(
                attempt_id=attempt.id,
                artifact_id=artifact.id,
                job_id=job.id,
                path=payload.path,
                role=VerificationOutputRole(payload.role),
            )
        )
        return stored_artifact(artifact)


def completion_artifacts(
    session: Session, *, payload: ControllerCompletion, controller_id: str
) -> tuple[StoredArtifact, ...]:
    with transaction(session):
        job, _ = _controller_context(session, payload.job_id)
        existing = session.scalar(
            select(SqlVerificationResult).where(
                SqlVerificationResult.attempt_id == payload.attempt_id
            )
        )
        if existing:
            attempt = session.get(SqlVerificationAttempt, payload.attempt_id)
            if (
                existing.job_id != job.id
                or attempt is None
                or attempt.controller_id != controller_id
                or attempt.generation != payload.generation
                or existing.completion_request_digest != request_digest(payload)
            ):
                raise DomainConflict("verification_completion_retry_mismatch")
            return ()
        _fence(session, job, payload, controller_id)
        validate_completion_limits(payload, _limits(job))
        return tuple(stored_artifact(a) for a in _output_rows(session, job, payload))


def _output_rows(
    session: Session, job: SqlVerificationJob, payload: ControllerCompletion
) -> list[SqlArtifact]:
    result = []
    for item in sorted(payload.outputs, key=lambda item: item.artifact_id):
        binding = session.get(SqlVerificationOutputArtifact, (payload.attempt_id, item.artifact_id))
        artifact = session.scalar(
            select(SqlArtifact)
            .where(SqlArtifact.id == item.artifact_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            binding is None
            or artifact is None
            or binding.job_id != job.id
            or binding.path != item.path
            or binding.role.value != item.role
            or artifact.sha256 != item.sha256
            or artifact.byte_length != item.byte_length
            or artifact.state != ArtifactState.STAGING
            or utc(artifact.expires_at) <= utc_now()
        ):
            raise DomainConflict("verification_output_binding")
        result.append(artifact)
    return result


def complete(
    session: Session,
    *,
    payload: ControllerCompletion,
    controller_id: str,
    verified_artifacts: tuple[StoredArtifact, ...],
) -> JobRead:
    """Internal service boundary: verified_artifacts comes only from byte I/O, never JSON."""
    with transaction(session):
        job, project_id = _controller_context(session, payload.job_id)
        existing = session.scalar(
            select(SqlVerificationResult).where(
                SqlVerificationResult.attempt_id == payload.attempt_id
            )
        )
        if existing:
            attempt = session.get(SqlVerificationAttempt, payload.attempt_id)
            if (
                existing.job_id != job.id
                or attempt is None
                or attempt.controller_id != controller_id
                or attempt.generation != payload.generation
                or existing.completion_request_digest != request_digest(payload)
            ):
                raise DomainConflict("verification_completion_retry_mismatch")
            return _snapshot(session, job, project_id)
        attempt = _fence(session, job, payload, controller_id)
        validate_completion_limits(payload, _limits(job))
        artifacts = _output_rows(session, job, payload)
        _fence(session, job, payload, controller_id)
        verified = {a.id: a for a in verified_artifacts}
        if set(verified) != {a.id for a in artifacts} or any(
            verified[a.id].integrity != ArtifactIntegrity(a.sha256, a.byte_length)
            or verified[a.id].storage_key != a.storage_key
            for a in artifacts
        ):
            raise DomainConflict("verification_outputs_not_verified")
        result = SqlVerificationResult(
            job_id=job.id,
            attempt_id=attempt.id,
            environment_id=job.environment_id,
            input_manifest_digest=job.manifest_digest,
            outcome=payload.outcome,
            diagnostic_summary={"code": payload.diagnostic_code, "exit_code": payload.exit_code},
            usage_summary={},
            completion_request_digest=request_digest(payload),
        )
        session.add(result)
        session.flush()
        for artifact in artifacts:
            artifact.state = ArtifactState.COMMITTED
            artifact.verified_at = utc_now()
            artifact.committed_at = utc_now()
            binding = session.get(SqlVerificationOutputArtifact, (attempt.id, artifact.id))
            assert binding is not None
            binding.result_id = result.id
        session.flush()
        contribution = session.get(SqlContributionEnvelope, job.contribution_id)
        if contribution is not None and contribution.run_id is not None:
            session.add_all(
                SqlRunArtifactOutput(
                    run_id=contribution.run_id,
                    artifact_id=artifact.id,
                    result_id=result.id,
                )
                for artifact in artifacts
            )
        _finish(
            session,
            job,
            VerificationJobState(payload.outcome),
            payload.diagnostic_code,
            attempt,
            acknowledged=True,
        )
        return _snapshot(session, job, project_id)
