"""Lifecycle regression tests. SQLite is not claim-contention evidence."""

from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from test_research_domain import create_object, create_project, current_user_id, headers

from polycolab.db.models import (
    SqlArtifact,
    SqlRunArtifactOutput,
    SqlVerificationAttempt,
    SqlVerificationEnvironment,
    SqlVerificationJob,
    SqlVerificationReservation,
)
from polycolab.entities.enums import ArtifactState, VerificationLanguage
from polycolab.entities.time import utc_now
from polycolab.projects.service import DomainConflict
from polycolab.verification import service as verification
from polycolab.verification.contracts import (
    ControllerCompletion,
    InputReference,
    JobPurpose,
    JobSubmission,
    OutputReference,
    OutputStageRequest,
    ResourceLimits,
)
from polycolab.verification.limits import QuotaExceeded
from polycolab.verification.version_contracts import VersionJobSubmission


def setup_job(client: TestClient) -> tuple[Any, UUID, JobSubmission]:
    app = cast(Any, client.app)
    project_id = UUID(create_project(client))
    source = create_object(client, str(project_id), kind="COMPUTATION", content="print(1)")
    user_id = UUID(current_user_id(client, "owner"))
    limits = ResourceLimits(
        cpu_count=1,
        cpu_seconds=10,
        wall_seconds=60,
        memory_bytes=16 * 1024 * 1024,
        process_count=4,
        disk_bytes=1024 * 1024,
        output_bytes=1024,
        log_bytes=1024,
        output_files=4,
    )
    with app.state.session_factory() as session:
        env = SqlVerificationEnvironment(
            language=VerificationLanguage.PYTHON,
            image_digest=uuid4().hex * 2,
            toolchain_version="test-pinned",
            dependency_lock_digest="b" * 64,
            build_digest="c" * 64,
            platform_identity="test-only",
            available=True,
            **{f"max_{key}": value for key, value in limits.model_dump().items()},
        )
        session.add(env)
        session.commit()
        environment_id = env.id
    app.state.settings.feature_verification_submission_enabled = True
    app.state.settings.verification_controller_token = SecretStr("test-controller-only")
    revision_id = UUID(source["current_object_version_id"])
    submission = JobSubmission(
        project_id=project_id,
        work_target_revision_id=revision_id,
        environment_id=environment_id,
        purpose=JobPurpose.PYTHON_RUN,
        evidence_scope="test reproduction",
        inputs=(InputReference(path="main.py", role="SOURCE", revision_id=revision_id),),
        entrypoint="main.py",
        limits=limits,
    )
    return app, user_id, submission


def admit(app: Any, user_id: UUID, submission: JobSubmission, key: str = "first") -> Any:
    with app.state.session_factory() as session:
        return verification.submit(
            session,
            user_id=user_id,
            submission=submission,
            retry_key=key,
            settings=app.state.settings,
        )


def claim(app: Any) -> Any:
    with app.state.session_factory() as session:
        result = verification.claim(
            session, controller_id="controller", settings=app.state.settings
        )
        assert result is not None
        return result


def completion(binding: Any) -> ControllerCompletion:
    return ControllerCompletion(
        job_id=binding.job_id,
        attempt_id=binding.attempt_id,
        generation=binding.generation,
        outcome="COMPLETED",
        exit_code=0,
        diagnostic_code="NONE",
    )


def test_admission_replay_quotas_and_exact_rerun(client: TestClient) -> None:
    app, user_id, submission = setup_job(client)
    first = admit(app, user_id, submission)
    assert admit(app, user_id, submission).id == first.id
    with pytest.raises(DomainConflict):
        admit(app, user_id, submission.model_copy(update={"seed": 2}))
    second = admit(app, user_id, submission, "second")
    with pytest.raises(QuotaExceeded):
        admit(app, user_id, submission, "third")
    with app.state.session_factory() as session:
        verification.cancel(
            session, job_id=second.id, project_id=submission.project_id, user_id=user_id
        )
        rerun = verification.rerun(
            session,
            job_id=second.id,
            project_id=submission.project_id,
            user_id=user_id,
            retry_key="third",
            settings=app.state.settings,
        )
        assert rerun.id != second.id
        assert rerun.submission == submission
        assert session.scalar(select(func.count()).select_from(SqlVerificationReservation)) == 3


def test_source_revision_kind_matches_the_requested_runner(client: TestClient) -> None:
    app, user_id, submission = setup_job(client)
    claim = create_object(client, str(submission.project_id), kind="CLAIM", content="print(2)")
    claim_revision = UUID(claim["current_object_version_id"])
    wrong_python = submission.model_copy(
        update={
            "inputs": (InputReference(path="main.py", role="SOURCE", revision_id=claim_revision),),
        }
    )
    with pytest.raises(DomainConflict, match="verification_source_kind_mismatch"):
        admit(app, user_id, wrong_python, "wrong-python-kind")

    formalization = create_object(
        client,
        str(submission.project_id),
        kind="FORMALIZATION",
        content="theorem identity (p : Prop) : p → p := by intro h; exact h",
    )
    formalization_revision = UUID(formalization["current_object_version_id"])
    with app.state.session_factory() as session:
        python_environment = session.get(SqlVerificationEnvironment, submission.environment_id)
        assert python_environment is not None
        lean_environment = SqlVerificationEnvironment(
            language=VerificationLanguage.LEAN,
            image_digest="d" * 64,
            toolchain_version="lean-test-pinned",
            dependency_lock_digest="e" * 64,
            build_digest="f" * 64,
            platform_identity="test-only",
            available=True,
            **{f"max_{key}": value for key, value in submission.limits.model_dump().items()},
        )
        session.add(lean_environment)
        session.commit()
        lean_environment_id = lean_environment.id
    lean = submission.model_copy(
        update={
            "work_target_revision_id": formalization_revision,
            "environment_id": lean_environment_id,
            "purpose": JobPurpose.LEAN_CHECK,
            "inputs": (
                InputReference(path="Main.lean", role="SOURCE", revision_id=formalization_revision),
            ),
            "entrypoint": "Main.lean",
        }
    )
    assert admit(app, user_id, lean, "lean-source-kind").submission == lean


def test_claim_complete_replay_and_events(client: TestClient) -> None:
    app, user_id, submission = setup_job(client)
    job = admit(app, user_id, submission)
    leased = claim(app)
    with app.state.session_factory() as session:
        assert (
            verification.claim(session, controller_id="other", settings=app.state.settings) is None
        )
        data = verification.input_bytes(
            session, binding=leased, controller_id="controller", position=0
        )
        assert data.data == b"print(1)"
        payload = completion(leased)
        result = verification.complete(
            session, payload=payload, controller_id="controller", verified_artifacts=()
        )
        replay = verification.complete(
            session, payload=payload, controller_id="controller", verified_artifacts=()
        )
        assert result == replay
        assert result.state == "COMPLETED"
        with pytest.raises(DomainConflict):
            verification.complete(
                session,
                payload=payload.model_copy(
                    update={"outcome": "FAILED", "diagnostic_code": "PROGRAM_ERROR"}
                ),
                controller_id="controller",
                verified_artifacts=(),
            )
        with pytest.raises(DomainConflict):
            verification.renew(
                session,
                binding=leased,
                controller_id="controller",
                settings=app.state.settings,
            )
        events = verification.events(
            session,
            job_id=job.id,
            project_id=submission.project_id,
            user_id=user_id,
            after=1,
            limit=100,
            settings=app.state.settings,
        )
        assert [event.sequence for event in events] == [2, 3]


def test_cancellation_fences_outputs_and_retains_capacity(client: TestClient) -> None:
    app, user_id, submission = setup_job(client)
    job = admit(app, user_id, submission)
    leased = claim(app)
    stage = OutputStageRequest(
        job_id=job.id,
        attempt_id=leased.attempt_id,
        generation=leased.generation,
        path="result.txt",
        role="OUTPUT",
        sha256="a" * 64,
        byte_length=4,
    )
    with app.state.session_factory() as session:
        output = verification.stage(
            session,
            payload=stage,
            controller_id="controller",
            settings=app.state.settings,
        )
        verification.cancel(
            session, job_id=job.id, project_id=submission.project_id, user_id=user_id
        )
        for operation in (
            lambda: verification.renew(
                session,
                binding=leased,
                controller_id="controller",
                settings=app.state.settings,
            ),
            lambda: verification.stage(
                session,
                payload=stage,
                controller_id="controller",
                settings=app.state.settings,
            ),
            lambda: verification.complete(
                session,
                payload=completion(leased),
                controller_id="controller",
                verified_artifacts=(),
            ),
        ):
            with pytest.raises(DomainConflict):
                operation()
        artifact = session.get(SqlArtifact, output.id)
        assert artifact is not None and artifact.state == ArtifactState.STAGING
        reservation = session.get(SqlVerificationReservation, job.id)
        assert reservation is not None and verification.utc(reservation.accounted_at) > utc_now()
    app.state.settings.verification_user_concurrent_jobs = 1
    with pytest.raises(QuotaExceeded):
        admit(app, user_id, submission, "replacement")


def test_lease_recovery_waits_for_wall_bound_and_rejects_old_generation(
    client: TestClient,
) -> None:
    app, user_id, submission = setup_job(client)
    admit(app, user_id, submission)
    leased = claim(app)
    with app.state.session_factory() as session:
        attempt = session.get(SqlVerificationAttempt, leased.attempt_id)
        assert attempt is not None
        attempt.lease_expires_at = utc_now() - timedelta(seconds=1)
        session.commit()
        assert verification.recover(session) == 1
        assert (
            verification.claim(session, controller_id="controller", settings=app.state.settings)
            is None
        )
        attempt = session.get(SqlVerificationAttempt, leased.attempt_id)
        assert attempt is not None
        # SQLite fixture-only clock adjustment; PostgreSQL tests advance the clock.
        attempt.started_at = utc_now() - timedelta(seconds=61)
        session.commit()
    replacement = claim(app)
    assert replacement.generation == 2
    with app.state.session_factory() as session:
        with pytest.raises(DomainConflict):
            verification.complete(
                session,
                payload=completion(leased),
                controller_id="controller",
                verified_artifacts=(),
            )
        assert (
            verification.complete(
                session,
                payload=completion(replacement),
                controller_id="controller",
                verified_artifacts=(),
            ).state
            == "COMPLETED"
        )


def test_output_binding_integrity_and_limits(client: TestClient) -> None:
    app, user_id, submission = setup_job(client)
    admit(app, user_id, submission)
    leased = claim(app)
    payload = OutputStageRequest(
        job_id=leased.job_id,
        attempt_id=leased.attempt_id,
        generation=leased.generation,
        path="result.txt",
        role="OUTPUT",
        sha256="a" * 64,
        byte_length=4,
    )
    with app.state.session_factory() as session:
        output = verification.stage(
            session,
            payload=payload,
            controller_id="controller",
            settings=app.state.settings,
        )
        assert (
            verification.stage(
                session,
                payload=payload,
                controller_id="controller",
                settings=app.state.settings,
            )
            == output
        )
        with pytest.raises(DomainConflict):
            verification.stage(
                session,
                payload=payload.model_copy(update={"sha256": "b" * 64}),
                controller_id="controller",
                settings=app.state.settings,
            )
        done = completion(leased).model_copy(
            update={
                "outputs": (
                    OutputReference(
                        artifact_id=output.id,
                        path=payload.path,
                        role="OUTPUT",
                        sha256=payload.sha256,
                        byte_length=4,
                    ),
                )
            }
        )
        with pytest.raises(DomainConflict):
            verification.complete(
                session, payload=done, controller_id="controller", verified_artifacts=()
            )
        assert verification.completion_artifacts(
            session, payload=done, controller_id="controller"
        ) == (output,)
        result = verification.complete(
            session,
            payload=done,
            controller_id="controller",
            verified_artifacts=(output,),
        )
        assert result.results[0].outputs[0].artifact_id == output.id
        assert session.get(SqlArtifact, output.id).state == ArtifactState.COMMITTED
        assert session.scalar(select(func.count()).select_from(SqlRunArtifactOutput)) == 0


def test_http_authentication_private_schema_and_disabled_execution(
    client: TestClient,
) -> None:
    app, _, submission = setup_job(client)
    assert not any(path.startswith("/internal/verification") for path in app.openapi()["paths"])
    url = f"/api/v1/projects/{submission.project_id}/verification-jobs"
    payload = {
        "retry_key": "http",
        "submission": VersionJobSubmission.from_stored(submission).model_dump(mode="json"),
    }
    assert (
        client.post(url, headers=headers("test-controller-only"), json=payload).status_code == 401
    )
    response = client.post(url, headers=headers("owner"), json=payload)
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]
    assert client.get(f"{url}/{job_id}", headers=headers("outsider")).status_code == 404
    assert client.post("/internal/verification/claim", headers=headers("owner")).status_code == 401
    assert (
        client.post(
            "/internal/verification/claim", headers=headers("test-controller-only")
        ).status_code
        == 503
    )
    assert (
        client.get(
            f"{url}/{job_id}/events?after_sequence=0&limit=1", headers=headers("owner")
        ).json()[0]["sequence"]
        == 1
    )


def test_available_environment_discovery_is_authorized_bounded_and_exact(
    client: TestClient,
) -> None:
    app, _, submission = setup_job(client)
    with app.state.session_factory() as session:
        first = session.get(SqlVerificationEnvironment, submission.environment_id)
        assert first is not None

        def environment(digest: str, *, available: bool) -> SqlVerificationEnvironment:
            return SqlVerificationEnvironment(
                language=VerificationLanguage.PYTHON,
                image_digest=digest * 64,
                toolchain_version=f"python-{digest}",
                dependency_lock_digest="e" * 64,
                build_digest="f" * 64,
                platform_identity="linux-test",
                available=available,
                **{f"max_{key}": value for key, value in submission.limits.model_dump().items()},
            )

        second = environment("1", available=True)
        unavailable = environment("2", available=False)
        session.add_all([second, unavailable])
        session.commit()
        expected = sorted((first.id, second.id))

    app.state.settings.feature_verification_submission_enabled = False
    url = f"/api/v1/projects/{submission.project_id}/verification-environments"
    assert client.get(url, headers=headers("outsider")).status_code == 404
    assert client.get(url).status_code == 401
    first_page = client.get(
        url,
        headers=headers("owner"),
        params={"limit": 1, "language": "PYTHON"},
    )
    assert first_page.status_code == 200
    assert first_page.headers["cache-control"] == "private, no-store"
    first_payload = first_page.json()
    assert [UUID(item["id"]) for item in first_payload["items"]] == expected[:1]
    assert UUID(first_payload["next_after"]) == expected[0]
    item = first_payload["items"][0]
    assert set(item) == {
        "id",
        "language",
        "image_digest",
        "toolchain_version",
        "dependency_lock_digest",
        "build_digest",
        "platform_identity",
        "limits",
        "created_at",
        "availability_changed_at",
    }
    assert item["limits"] == submission.limits.model_dump(mode="json")
    second_page = client.get(
        url,
        headers=headers("owner"),
        params={"limit": 1, "after": first_payload["next_after"]},
    ).json()
    assert [UUID(item["id"]) for item in second_page["items"]] == expected[1:]
    assert second_page["next_after"] is None
    assert client.get(
        url,
        headers=headers("owner"),
        params={"language": "LEAN"},
    ).json() == {"items": [], "next_after": None}


def test_deadline_and_environment_denial(client: TestClient) -> None:
    app, user_id, submission = setup_job(client)
    job = admit(app, user_id, submission)
    with app.state.session_factory() as session:
        row = session.get(SqlVerificationJob, job.id)
        assert row is not None
        row.deadline_at = utc_now() - timedelta(seconds=1)
        session.commit()
        assert verification.recover(session) == 1
        assert (
            verification.inspect(
                session,
                job_id=job.id,
                project_id=submission.project_id,
                user_id=user_id,
            ).state
            == "TIMED_OUT"
        )
        env = session.get(SqlVerificationEnvironment, submission.environment_id)
        assert env is not None
        env.available = False
        session.commit()
    with pytest.raises(DomainConflict):
        admit(app, user_id, submission, "new")


def test_revoked_sponsor_cannot_claim_or_complete(client: TestClient) -> None:
    from polycolab.access.authorization import ProjectNotFound
    from polycolab.db.models import SqlMembership

    app, user_id, submission = setup_job(client)
    first = admit(app, user_id, submission)
    leased = claim(app)
    second = admit(app, user_id, submission, "queued")
    with app.state.session_factory() as session:
        member = session.scalar(
            select(SqlMembership).where(
                SqlMembership.project_id == submission.project_id,
                SqlMembership.user_id == user_id,
            )
        )
        session.delete(member)
        session.commit()
        with pytest.raises(ProjectNotFound):
            verification.complete(
                session,
                payload=completion(leased),
                controller_id="controller",
                verified_artifacts=(),
            )
        assert (
            verification.claim(session, controller_id="controller", settings=app.state.settings)
            is None
        )
        assert session.get(SqlVerificationJob, second.id).terminal_reason == "AUTHORITY_REVOKED"
        assert session.get(SqlVerificationJob, first.id).state.value == "RUNNING"


def test_http_body_bound_and_reads_after_submission_disabled(
    client: TestClient,
) -> None:
    app, user_id, submission = setup_job(client)
    job = admit(app, user_id, submission)
    url = f"/api/v1/projects/{submission.project_id}/verification-jobs"
    app.state.settings.verification_api_max_request_bytes = 32
    response = client.post(
        url,
        headers={**headers("owner"), "Content-Type": "application/json"},
        content=b" " * 33,
    )
    assert response.status_code == 413
    app.state.settings.feature_verification_submission_enabled = False
    assert client.get(f"{url}/{job.id}", headers=headers("owner")).status_code == 200
    assert client.post(f"{url}/{job.id}/cancel", headers=headers("owner")).status_code == 200
    app.state.settings.verification_api_max_response_bytes = 32
    assert client.get(f"{url}/{job.id}", headers=headers("owner")).status_code == 503


def test_agent_tools_require_explicit_capability_and_pin_run_scope(
    client: TestClient,
) -> None:
    from test_direct_contributions import active_run

    from polycolab.agents.sessions import append_worker_event
    from polycolab.agents.tools import ToolCapabilityInvalid, execute_tool
    from polycolab.db.models import (
        AgentRunEventKind,
        SqlAgentRun,
        SqlContextManifest,
        SqlContributionEnvelope,
        SqlRunToolCapability,
    )
    from polycolab.verification import tools as verification_tools

    app, user_id, submission = setup_job(client)
    _, denied_token, _, _, _ = active_run(
        client, public=False, project_id=str(submission.project_id)
    )
    with app.state.session_factory() as session:
        with pytest.raises(ToolCapabilityInvalid):
            verification_tools.execute(
                session,
                token=denied_token,
                name="submit_verification",
                project_id=submission.project_id,
                settings=app.state.settings,
                submission=submission,
                retry_key="denied",
            )

    from polycolab.db.models import SqlResearchScope
    from polycolab.research.contributions import human_contribution

    with app.state.session_factory() as session:
        scope = session.scalar(
            select(SqlResearchScope).where(SqlResearchScope.project_id == submission.project_id)
        )
        assert scope is not None
        contribution = human_contribution(
            session,
            user_id=user_id,
            scope_id=scope.id,
            operation="test.context-artifact",
        )
        now = utc_now()

        def committed_artifact(digest: str) -> SqlArtifact:
            return SqlArtifact(
                ownership_scope_id=scope.id,
                contribution_id=contribution.id,
                created_by_user_id=user_id,
                sha256=digest * 64,
                byte_length=3,
                media_type="application/octet-stream",
                storage_key=f"test/{uuid4()}",
                state=ArtifactState.COMMITTED,
                expires_at=now + timedelta(days=1),
                verified_at=now,
                committed_at=now,
            )

        artifact = committed_artifact("a")
        unlisted_artifact = committed_artifact("b")
        session.add_all([artifact, unlisted_artifact])
        session.commit()
        artifact_id = artifact.id
        unlisted_artifact_id = unlisted_artifact.id
    submission = submission.model_copy(
        update={
            "inputs": (
                *submission.inputs,
                InputReference(path="input.bin", role="INPUT", artifact_id=artifact_id),
            )
        }
    )

    _, token, run_id, _, _ = active_run(
        client,
        public=False,
        project_id=str(submission.project_id),
        allowed_operations=["RUN_VERIFICATION"],
        context_revision_ids=[str(submission.work_target_revision_id)],
        context_artifact_ids=[str(artifact_id)],
    )
    with app.state.session_factory() as session:
        capability = session.scalar(
            select(SqlRunToolCapability).where(SqlRunToolCapability.run_id == run_id)
        )
        assert capability is not None
        assert set(capability.allowed_tools) >= verification_tools.TOOL_NAMES
        from polycolab.agents.context import manifest_artifacts

        manifest = session.get(SqlContextManifest, capability.context_manifest_id)
        assert manifest is not None
        assert [row.id for row in manifest_artifacts(session, manifest=manifest)] == [artifact_id]
        context = execute_tool(session, token=token, name="get_context", arguments={})
        assert context["artifacts"] == [
            {
                "id": str(artifact_id),
                "sha256": "a" * 64,
                "byte_length": 3,
                "media_type": "application/octet-stream",
            }
        ]
        run = session.get(SqlAgentRun, run_id)
        assert run is not None
        requested = append_worker_event(
            session,
            run_id=run_id,
            worker_id="direct-test",
            lease_generation=run.lease_generation,
            kind=AgentRunEventKind.TOOL_REQUESTED,
            idempotency_key="agent-requested",
            payload={"tool_name": "submit_verification"},
        )
        submit_cursor = requested.cursor
        unlisted_requested = append_worker_event(
            session,
            run_id=run_id,
            worker_id="direct-test",
            lease_generation=run.lease_generation,
            kind=AgentRunEventKind.TOOL_REQUESTED,
            idempotency_key="unlisted-requested",
            payload={"tool_name": "submit_verification"},
        )
        unlisted_cursor = unlisted_requested.cursor

    tool_url = "/internal/v1/tools/call"
    tool_headers = {
        "Authorization": f"Bearer {token}",
        "X-Polycolab-Tool-Invocation": "agent",
        "X-Polycolab-Source-Event-Cursor": str(submit_cursor),
    }
    unlisted_submission = submission.model_copy(
        update={
            "inputs": (
                *submission.inputs[:-1],
                InputReference(path="input.bin", role="INPUT", artifact_id=unlisted_artifact_id),
            )
        }
    )
    assert (
        client.post(
            tool_url,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Polycolab-Tool-Invocation": "unlisted",
                "X-Polycolab-Source-Event-Cursor": str(unlisted_cursor),
            },
            json={
                "name": "submit_verification",
                "arguments": VersionJobSubmission.from_stored(unlisted_submission).model_dump(
                    mode="json"
                ),
            },
        ).status_code
        == 401
    )
    request = {
        "name": "submit_verification",
        "arguments": VersionJobSubmission.from_stored(submission).model_dump(mode="json"),
    }
    response = client.post(tool_url, headers=tool_headers, json=request)
    assert response.status_code == 200, response.text
    job = response.json()
    assert client.post(tool_url, headers=tool_headers, json=request).json()["id"] == job["id"]
    inspected = client.post(
        tool_url,
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "inspect_verification", "arguments": {"job_id": job["id"]}},
    )
    assert inspected.status_code == 200 and inspected.json()["id"] == job["id"]
    with app.state.session_factory() as session:
        envelope = session.get(
            SqlContributionEnvelope,
            session.get(SqlVerificationJob, UUID(job["id"])).contribution_id,
        )
        assert envelope.run_id == run_id and envelope.actor_kind.value == "AGENT"
        assert envelope.source_event_cursors == [submit_cursor]
        run = session.get(SqlAgentRun, run_id)
        assert run is not None
        cancelled_event = append_worker_event(
            session,
            run_id=run_id,
            worker_id="direct-test",
            lease_generation=run.lease_generation,
            kind=AgentRunEventKind.TOOL_REQUESTED,
            idempotency_key="cancel-agent-requested",
            payload={"tool_name": "cancel_verification"},
        )
        cancel_cursor = cancelled_event.cursor
    assert (
        client.post(
            tool_url,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Polycolab-Tool-Invocation": "cancel-agent",
                "X-Polycolab-Source-Event-Cursor": str(submit_cursor),
            },
            json={"name": "cancel_verification", "arguments": {"job_id": job["id"]}},
        ).status_code
        == 401
    )
    cancelled = client.post(
        tool_url,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Polycolab-Tool-Invocation": "cancel-agent",
            "X-Polycolab-Source-Event-Cursor": str(cancel_cursor),
        },
        json={"name": "cancel_verification", "arguments": {"job_id": job["id"]}},
    )
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "CANCELLED"
    with app.state.session_factory() as session:
        capability = session.scalar(
            select(SqlRunToolCapability).where(SqlRunToolCapability.run_id == run_id)
        )
        assert capability is not None
        capability = session.get(SqlRunToolCapability, capability.id)
        capability.revoked = True
        session.commit()
    assert (
        client.post(
            tool_url,
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "inspect_verification", "arguments": {"job_id": job["id"]}},
        ).status_code
        == 401
    )


def test_agent_verification_output_becomes_exact_same_run_artifact_scope(
    client: TestClient,
) -> None:
    from test_direct_contributions import active_run

    from polycolab.access.authorization import AuthorizationDenied
    from polycolab.agents.sessions import append_worker_event
    from polycolab.agents.tools import execute_tool
    from polycolab.db.models import AgentRunEventKind, SqlAgentRun
    from polycolab.verification import tools as verification_tools

    app, _, submission = setup_job(client)
    _, token, run_id, _, _ = active_run(
        client,
        public=False,
        project_id=str(submission.project_id),
        allowed_operations=["RUN_VERIFICATION"],
        context_revision_ids=[str(submission.work_target_revision_id)],
    )

    def invocation(key: str, tool_name: str, current_run_id: UUID) -> int:
        with app.state.session_factory() as session:
            run = session.get(SqlAgentRun, current_run_id)
            assert run is not None
            return append_worker_event(
                session,
                run_id=current_run_id,
                worker_id="direct-test",
                lease_generation=run.lease_generation,
                kind=AgentRunEventKind.TOOL_REQUESTED,
                idempotency_key=f"{key}-requested",
                payload={"tool_name": tool_name},
            ).cursor

    with app.state.session_factory() as session:
        first = verification_tools.execute(
            session,
            token=token,
            name="submit_verification",
            project_id=submission.project_id,
            settings=app.state.settings,
            submission=submission,
            retry_key="first-agent-job",
            invocation_key="first-agent-job",
            source_event_cursor=invocation("first-agent-job", "submit_verification", run_id),
        )
    leased = claim(app)
    declaration = OutputStageRequest(
        job_id=first.id,
        attempt_id=leased.attempt_id,
        generation=leased.generation,
        path="result.bin",
        role="OUTPUT",
        sha256="d" * 64,
        byte_length=4,
    )
    with app.state.session_factory() as session:
        output = verification.stage(
            session,
            payload=declaration,
            controller_id="controller",
            settings=app.state.settings,
        )
        done = completion(leased).model_copy(
            update={
                "outputs": (
                    OutputReference(
                        artifact_id=output.id,
                        path=declaration.path,
                        role=declaration.role,
                        sha256=declaration.sha256,
                        byte_length=declaration.byte_length,
                    ),
                )
            }
        )
        verification.complete(
            session,
            payload=done,
            controller_id="controller",
            verified_artifacts=(output,),
        )
        binding = session.get(SqlRunArtifactOutput, (run_id, output.id))
        assert binding is not None
        context = execute_tool(session, token=token, name="get_context", arguments={})
        assert context["artifacts"] == [
            {
                "id": str(output.id),
                "sha256": "d" * 64,
                "byte_length": 4,
                "media_type": "application/octet-stream",
            }
        ]

    chained = submission.model_copy(
        update={
            "inputs": (
                *submission.inputs,
                InputReference(path="result.bin", role="INPUT", artifact_id=output.id),
            )
        }
    )
    with app.state.session_factory() as session:
        second = verification_tools.execute(
            session,
            token=token,
            name="submit_verification",
            project_id=submission.project_id,
            settings=app.state.settings,
            submission=chained,
            retry_key="chained-agent-job",
            invocation_key="chained-agent-job",
            source_event_cursor=invocation("chained-agent-job", "submit_verification", run_id),
        )
        assert second.submission.inputs[-1].artifact_id == output.id

    _, other_token, other_run_id, _, _ = active_run(
        client,
        public=False,
        project_id=str(submission.project_id),
        allowed_operations=["RUN_VERIFICATION"],
        context_revision_ids=[str(submission.work_target_revision_id)],
    )
    with app.state.session_factory() as session:
        with pytest.raises(AuthorizationDenied):
            verification_tools.execute(
                session,
                token=other_token,
                name="submit_verification",
                project_id=submission.project_id,
                settings=app.state.settings,
                submission=chained,
                retry_key="other-run-job",
                invocation_key="other-run-job",
                source_event_cursor=invocation(
                    "other-run-job", "submit_verification", other_run_id
                ),
            )
