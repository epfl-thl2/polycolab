"""Real PostgreSQL invariants for the shared Step 14 verification foundation."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from test_m0_postgresql import pg_schema as pg_schema
from test_research_domain import create_object, create_workspace

from polycolab.app.application import create_app
from polycolab.db.models import (
    SqlArtifact,
    SqlObjectRevision,
    SqlResearchAttemptRevision,
    SqlVerificationAttempt,
    SqlVerificationEnvironment,
    SqlVerificationEvent,
    SqlVerificationInput,
    SqlVerificationJob,
    SqlVerificationOutputArtifact,
    SqlVerificationReservation,
    SqlVerificationResult,
)
from polycolab.entities.enums import (
    ArtifactState,
    VerificationAttemptState,
    VerificationInputRole,
    VerificationJobState,
    VerificationLanguage,
    VerificationOutputRole,
    VerificationReservationState,
)
from polycolab.platform.config import Settings


def _artifact(revision: SqlObjectRevision, *, state: ArtifactState) -> SqlArtifact:
    now = datetime.now(UTC)
    committed = state is ArtifactState.COMMITTED
    return SqlArtifact(
        ownership_scope_id=revision.ownership_scope_id,
        contribution_id=revision.contribution_id,
        created_by_user_id=revision.created_by_user_id,
        sha256="a" * 64,
        byte_length=4,
        media_type="text/plain",
        storage_key=f"verification/{uuid4()}",
        state=state,
        expires_at=now + timedelta(hours=1),
        verified_at=now if committed else None,
        committed_at=now if committed else None,
    )


def _job(
    revision: SqlObjectRevision,
    environment: SqlVerificationEnvironment,
    *,
    attempt_revision_id: UUID | None = None,
) -> SqlVerificationJob:
    return SqlVerificationJob(
        ownership_scope_id=revision.ownership_scope_id,
        sponsor_user_id=revision.created_by_user_id,
        contribution_id=revision.contribution_id,
        work_target_revision_id=revision.id,
        research_attempt_revision_id=attempt_revision_id,
        environment_id=environment.id,
        purpose="PYTHON_RUN",
        evidence_scope="bounded reproduction",
        entrypoint="src/main.py",
        arguments=["--seed", "7"],
        seed=7,
        manifest_digest="b" * 64,
        request_digest="c" * 64,
        retry_key_digest=uuid4().hex * 2,
        contract_version=1,
        cpu_count=1,
        cpu_seconds=30,
        wall_seconds=60,
        memory_bytes=256 * 1024 * 1024,
        process_count=8,
        disk_bytes=128 * 1024 * 1024,
        output_bytes=1024,
        log_bytes=1024,
        output_files=4,
        max_attempts=2,
        deadline_at=datetime.now(UTC) + timedelta(minutes=10),
    )


def test_verification_foundation_preserves_exact_identity_and_history(
    pg_schema: tuple[Engine, Config, str], client: TestClient
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-verification-foundation-web"),
        cast(Any, client.app).state.identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            project_id = create_workspace(pg_client)
            attempt_record = create_object(pg_client, project_id, kind="ATTEMPT")
        with app.state.session_factory() as db:
            research_attempt = db.get(
                SqlResearchAttemptRevision, UUID(attempt_record["current_object_version_id"])
            )
            assert research_attempt is not None
            target = db.get(SqlObjectRevision, research_attempt.target_revision_id)
            assert target is not None
            environment = SqlVerificationEnvironment(
                language=VerificationLanguage.PYTHON,
                image_digest="1" * 64,
                toolchain_version="CPython 3.13.7",
                dependency_lock_digest="2" * 64,
                build_digest="3" * 64,
                platform_identity="linux-amd64-gvisor",
                max_cpu_count=2,
                max_cpu_seconds=600,
                max_wall_seconds=300,
                max_memory_bytes=1024 * 1024 * 1024,
                max_process_count=32,
                max_disk_bytes=1024 * 1024 * 1024,
                max_output_bytes=1024 * 1024,
                max_log_bytes=65_536,
                max_output_files=16,
            )
            db.add(environment)
            db.flush()
            job = _job(target, environment, attempt_revision_id=research_attempt.revision_id)
            db.add(job)
            db.flush()
            committed_input = _artifact(target, state=ArtifactState.COMMITTED)
            staged_output = _artifact(target, state=ArtifactState.STAGING)
            db.add_all((committed_input, staged_output))
            db.flush()
            db.add_all(
                (
                    SqlVerificationInput(
                        job_id=job.id,
                        position=0,
                        path="src/main.py",
                        role=VerificationInputRole.SOURCE,
                        revision_id=target.id,
                        sha256="4" * 64,
                    ),
                    SqlVerificationInput(
                        job_id=job.id,
                        position=1,
                        path="data/input.txt",
                        role=VerificationInputRole.INPUT,
                        artifact_id=committed_input.id,
                        sha256=committed_input.sha256,
                    ),
                    SqlVerificationReservation(
                        job_id=job.id,
                        sponsor_user_id=job.sponsor_user_id,
                        ownership_scope_id=job.ownership_scope_id,
                        cpu_seconds=job.cpu_seconds * job.max_attempts,
                        memory_byte_seconds=job.memory_bytes * job.wall_seconds * job.max_attempts,
                        disk_bytes=job.disk_bytes,
                        output_bytes=job.output_bytes,
                    ),
                )
            )
            db.commit()
            attempt = SqlVerificationAttempt(
                job_id=job.id,
                generation=1,
                controller_id="controller-a",
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
            )
            db.add(attempt)
            db.flush()
            job.state = VerificationJobState.RUNNING
            job.current_generation = 1
            job.event_sequence = 1
            db.add(
                SqlVerificationEvent(
                    job_id=job.id,
                    sequence=1,
                    attempt_id=attempt.id,
                    event_type="CLAIMED",
                    payload={"generation": 1},
                )
            )
            output = SqlVerificationOutputArtifact(
                attempt_id=attempt.id,
                artifact_id=staged_output.id,
                job_id=job.id,
                path="out/result.txt",
                role=VerificationOutputRole.OUTPUT,
            )
            db.add(output)
            db.commit()

            result = SqlVerificationResult(
                job_id=job.id,
                attempt_id=attempt.id,
                environment_id=environment.id,
                input_manifest_digest=job.manifest_digest,
                outcome="COMPLETED",
                diagnostic_summary={"code": "NONE"},
                usage_summary={"cpu_seconds": 2},
                completion_request_digest="5" * 64,
            )
            db.add(result)
            db.flush()
            now = datetime.now(UTC)
            staged_output.verified_at = now
            staged_output.state = ArtifactState.COMMITTED
            staged_output.committed_at = now
            output.result_id = result.id
            attempt.state = VerificationAttemptState.COMPLETED
            attempt.terminal_at = now
            job.state = VerificationJobState.COMPLETED
            job.terminal_at = now
            job.terminal_reason = "completed"
            job.event_sequence = 2
            reservation = db.get(SqlVerificationReservation, job.id)
            assert reservation is not None
            reservation.state = VerificationReservationState.RELEASED
            reservation.released_at = now
            reservation.accounted_at = now
            db.add(
                SqlVerificationEvent(
                    job_id=job.id,
                    sequence=2,
                    attempt_id=attempt.id,
                    event_type="COMPLETED",
                    payload={"result_id": str(result.id)},
                )
            )
            db.commit()

            environment.toolchain_version = "tampered"
            with pytest.raises(DBAPIError):
                db.commit()
            db.rollback()
            job = db.get(SqlVerificationJob, job.id)
            assert job is not None
            job.evidence_scope = "tampered"
            with pytest.raises(DBAPIError):
                db.commit()
            db.rollback()
            result = db.get(SqlVerificationResult, result.id)
            assert result is not None
            result.outcome = "FAILED"
            with pytest.raises(DBAPIError):
                db.commit()
            db.rollback()
            reservation = db.get(SqlVerificationReservation, job.id)
            assert reservation is not None
            reservation.released_at = datetime.now(UTC) + timedelta(seconds=1)
            with pytest.raises(DBAPIError):
                db.commit()
            db.rollback()
    finally:
        app.state.engine.dispose()


def test_verification_foundation_rejects_incoherent_targets_and_artifact_states(
    pg_schema: tuple[Engine, Config, str], client: TestClient
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-verification-foundation-web"),
        cast(Any, client.app).state.identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            project_id = create_workspace(pg_client)
            target_record = create_object(pg_client, project_id)
            attempt_record = create_object(pg_client, project_id, kind="ATTEMPT")
        with app.state.session_factory() as db:
            target = db.get(SqlObjectRevision, UUID(target_record["current_object_version_id"]))
            research_attempt = db.get(
                SqlResearchAttemptRevision, UUID(attempt_record["current_object_version_id"])
            )
            assert target is not None and research_attempt is not None
            environment = SqlVerificationEnvironment(
                language=VerificationLanguage.PYTHON,
                image_digest="6" * 64,
                toolchain_version="CPython 3.13.7",
                dependency_lock_digest="7" * 64,
                build_digest="8" * 64,
                platform_identity="linux-amd64-gvisor",
                max_cpu_count=1,
                max_cpu_seconds=300,
                max_wall_seconds=300,
                max_memory_bytes=1024 * 1024 * 1024,
                max_process_count=32,
                max_disk_bytes=1024 * 1024 * 1024,
                max_output_bytes=1024 * 1024,
                max_log_bytes=65_536,
                max_output_files=16,
            )
            db.add(environment)
            db.flush()
            environment_id = environment.id
            target_id = target.id
            db.add(_job(target, environment, attempt_revision_id=research_attempt.revision_id))
            with pytest.raises(DBAPIError):
                db.commit()
            db.rollback()

            target = db.get(SqlObjectRevision, target_id)
            assert target is not None
            environment = SqlVerificationEnvironment(
                id=environment_id,
                language=VerificationLanguage.PYTHON,
                image_digest="6" * 64,
                toolchain_version="CPython 3.13.7",
                dependency_lock_digest="7" * 64,
                build_digest="8" * 64,
                platform_identity="linux-amd64-gvisor",
                max_cpu_count=1,
                max_cpu_seconds=300,
                max_wall_seconds=300,
                max_memory_bytes=1024 * 1024 * 1024,
                max_process_count=32,
                max_disk_bytes=1024 * 1024 * 1024,
                max_output_bytes=1024 * 1024,
                max_log_bytes=65_536,
                max_output_files=16,
            )
            db.add(environment)
            db.flush()
            job = _job(target, environment)
            db.add(job)
            db.flush()
            staged = _artifact(target, state=ArtifactState.STAGING)
            db.add(staged)
            db.flush()
            db.add(
                SqlVerificationInput(
                    job_id=job.id,
                    position=0,
                    path="src/main.py",
                    role=VerificationInputRole.SOURCE,
                    artifact_id=staged.id,
                    sha256=staged.sha256,
                )
            )
            with pytest.raises(DBAPIError):
                db.commit()
            db.rollback()
    finally:
        app.state.engine.dispose()
