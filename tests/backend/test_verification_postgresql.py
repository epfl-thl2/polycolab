"""Real PostgreSQL admission/claim/completion races against migrated constraints."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from test_verification import (
    admit,
    claim,
    completion,
    setup_job,
)
from test_verification import (
    test_admission_replay_quotas_and_exact_rerun as admission_case,
)
from test_verification import (
    test_agent_tools_require_explicit_capability_and_pin_run_scope as agent_artifact_case,
)
from test_verification import (
    test_agent_verification_output_becomes_exact_same_run_artifact_scope as agent_output_case,
)
from test_verification import (
    test_cancellation_fences_outputs_and_retains_capacity as cancel_case,
)
from test_verification import (
    test_claim_complete_replay_and_events as completion_case,
)
from test_verification import (
    test_output_binding_integrity_and_limits as output_case,
)
from test_verification_queue import (
    test_claim_reaches_quiet_user_behind_full_page_of_cooling_retries as queue_page_case,
)

from polycolab.accounts.authentication import MappingIdentityVerifier
from polycolab.app.application import create_app
from polycolab.db.models import (
    SqlAgentRun,
    SqlArtifact,
    SqlContextManifest,
    SqlContextManifestArtifact,
    SqlResearchScope,
    SqlRunArtifactOutput,
    SqlVerificationAttempt,
    SqlVerificationReservation,
    SqlVerificationResult,
)
from polycolab.entities.time import utc_now
from polycolab.platform.config import Settings
from polycolab.verification import service as verification
from polycolab.verification.limits import QuotaExceeded
from polycolab.workspaces.service import DomainConflict


@pytest.mark.parametrize("case", [admission_case, completion_case, cancel_case, output_case])
def test_migrated_lifecycle(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier, case: Any
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-verification-test"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            case(pg_client)
    finally:
        app.state.engine.dispose()


def test_migrated_interleaved_candidate_page(
    pg_schema: tuple[Engine, Config, str],
    identity_verifier: MappingIdentityVerifier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-verification-test"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            queue_page_case(pg_client, monkeypatch)
    finally:
        app.state.engine.dispose()


def test_migrated_lease_loss_and_attempt_exhaustion(
    pg_schema: tuple[Engine, Config, str],
    identity_verifier: MappingIdentityVerifier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-verification-test"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            app, user_id, submission = setup_job(pg_client)
        job = admit(app, user_id, submission)
        leased = claim(app)
        # Advance the service clock, never mutate immutable attempt timestamps.
        now = utc_now()
        monkeypatch.setattr(verification, "utc_now", lambda: now + timedelta(seconds=31))
        with app.state.session_factory() as session:
            assert verification.recover(session) == 1
            assert (
                verification.claim(session, controller_id="controller", settings=app.state.settings)
                is None
            )
        monkeypatch.setattr(verification, "utc_now", lambda: now + timedelta(seconds=61))
        second = claim(app)
        assert second.generation == 2
        with app.state.session_factory() as session:
            with pytest.raises(DomainConflict):
                verification.complete(
                    session,
                    payload=completion(leased),
                    controller_id="controller",
                    verified_artifacts=(),
                )
        monkeypatch.setattr(verification, "utc_now", lambda: now + timedelta(seconds=92))
        with app.state.session_factory() as session:
            assert verification.recover(session) == 1
            result = verification.inspect(
                session,
                job_id=job.id,
                project_id=submission.project_id,
                user_id=user_id,
            )
            assert result.state == "FAILED" and result.terminal_reason == "ATTEMPTS_EXHAUSTED"
            assert len(result.results) == 2
            assert verification.recover(session) == 0
    finally:
        app.state.engine.dispose()


def test_migrated_agent_artifact_manifest_and_late_member_rejection(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-verification-test"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            agent_artifact_case(pg_client)
        with app.state.session_factory() as session:
            manifest = next(
                item for item in session.scalars(select(SqlContextManifest)) if item.artifact_ids
            )
            scope = session.scalar(
                select(SqlResearchScope).where(SqlResearchScope.project_id == manifest.project_id)
            )
            assert scope is not None
            selected = {UUID(value) for value in manifest.artifact_ids}
            unlisted = session.scalar(
                select(SqlArtifact).where(
                    SqlArtifact.ownership_scope_id == scope.id,
                    SqlArtifact.id.not_in(selected),
                )
            )
            assert unlisted is not None
            session.add(
                SqlContextManifestArtifact(
                    manifest_id=manifest.id,
                    artifact_id=unlisted.id,
                    position=len(selected),
                )
            )
            with pytest.raises(SQLAlchemyError):
                session.commit()
            session.rollback()
    finally:
        app.state.engine.dispose()


def test_migrated_agent_output_scope_and_attribution_rejection(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-verification-test"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            agent_output_case(pg_client)
        with app.state.session_factory() as session:
            binding = session.scalars(select(SqlRunArtifactOutput)).one()
            other_run_id = session.scalar(
                select(SqlAgentRun.id).where(SqlAgentRun.id != binding.run_id)
            )
            assert other_run_id is not None
            session.add(
                SqlRunArtifactOutput(
                    run_id=other_run_id,
                    artifact_id=binding.artifact_id,
                    result_id=binding.result_id,
                )
            )
            with pytest.raises(SQLAlchemyError, match="run artifact output attribution mismatch"):
                session.commit()
            session.rollback()
    finally:
        app.state.engine.dispose()


def test_concurrent_admission_claim_completion_and_cancel(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-verification-test"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            app, user_id, submission = setup_job(pg_client)
        app.state.settings.verification_user_concurrent_jobs = 1
        barrier = Barrier(2)

        def submit_same() -> Any:
            barrier.wait(timeout=10)
            return admit(app, user_id, submission)

        with ThreadPoolExecutor(2) as pool:
            jobs = list(pool.map(lambda _: submit_same(), range(2)))
        assert jobs[0].id == jobs[1].id
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(SqlVerificationReservation)) == 1
        barrier = Barrier(2)

        def competing_claim(identity: str) -> Any:
            barrier.wait(timeout=10)
            with app.state.session_factory() as session:
                return verification.claim(
                    session, controller_id=identity, settings=app.state.settings
                )

        with ThreadPoolExecutor(2) as pool:
            claims = list(pool.map(competing_claim, ("controller", "controller")))
        leased = next(item for item in claims if item is not None)
        assert sum(item is not None for item in claims) == 1
        payload = completion(leased)
        barrier = Barrier(2)

        def completing() -> Any:
            barrier.wait(timeout=10)
            with app.state.session_factory() as session:
                return verification.complete(
                    session,
                    payload=payload,
                    controller_id="controller",
                    verified_artifacts=(),
                )

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: completing(), range(2)))
        assert results[0] == results[1]
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(SqlVerificationAttempt)) == 1
            assert session.scalar(select(func.count()).select_from(SqlVerificationResult)) == 1
        barrier = Barrier(2)

        def competing_admission(key: str) -> Any:
            barrier.wait(timeout=10)
            try:
                return admit(app, user_id, submission, key)
            except QuotaExceeded:
                return None

        with ThreadPoolExecutor(2) as pool:
            admissions = list(pool.map(competing_admission, ("next-a", "next-b")))
        assert sum(item is not None for item in admissions) == 1
        next_job = next(item for item in admissions if item is not None)
        leased = claim(app)
        payload = completion(leased)
        barrier = Barrier(2)

        def cancel_or_complete(cancel: bool) -> Any:
            barrier.wait(timeout=10)
            with app.state.session_factory() as session:
                if cancel:
                    return verification.cancel(
                        session,
                        job_id=next_job.id,
                        project_id=submission.project_id,
                        user_id=user_id,
                    )
                try:
                    return verification.complete(
                        session,
                        payload=payload,
                        controller_id="controller",
                        verified_artifacts=(),
                    )
                except DomainConflict:
                    return None

        with ThreadPoolExecutor(2) as pool:
            raced = list(pool.map(cancel_or_complete, (True, False)))
        assert raced[0].state in {"COMPLETED", "CANCELLED"}
        if raced[0].state == "CANCELLED":
            assert raced[1] is None
    finally:
        app.state.engine.dispose()
