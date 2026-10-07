from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import StringIO
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from polycolab.agents.runtime.messages import model_messages
from polycolab.agents.schemas import AgentSessionCreate
from polycolab.agents.sessions import (
    CRITIC_VERSION_ID,
    RESEARCHER_VERSION_ID,
    IdempotencyConflict,
    LeaseLost,
    SessionStateError,
    activate_runtime_session_binding,
    append_user_message_and_queue_run,
    append_worker_event,
    claim_next_run,
    claim_next_run_in_transaction,
    create_agent_session,
    create_runtime_run_binding,
    finish_run,
    platform_agent_version,
    record_usage,
    request_cancel,
    requeue_expired_runs,
    resume_run,
    start_claimed_run,
)
from polycolab.db.models import (
    SqlAgentMessage,
    SqlAgentRun,
    SqlAgentRunEvent,
    SqlGatewayProfile,
    SqlProject,
    SqlUser,
)
from polycolab.entities.enums import (
    AgentRunEventKind,
    AgentRunStatus,
    PlatformAgentKind,
    RuntimeBindingStatus,
    UsageSource,
    WorkspaceVisibility,
)


def _domain_setup(client: TestClient) -> tuple[Any, SqlUser, SqlProject, SqlGatewayProfile]:
    app = cast(Any, client.app)
    session = app.state.session_factory()
    user = SqlUser(issuer="https://issuer.example", subject="worker-owner", email="owner@test")
    session.add(user)
    session.commit()
    project = SqlProject(
        name="Runtime research",
        visibility=WorkspaceVisibility.PRIVATE,
        created_by_user_id=user.id,
    )
    session.add(project)
    session.commit()
    profile = SqlGatewayProfile(
        user_id=user.id,
        display_name="Test profile",
        base_url="https://models.example/v1",
        model_id="test-model",
        credential_version=3,
        encrypted_credential=b"ciphertext",
        wrapped_data_key=b"wrapped",
        encryption_key_version="test-key-v1",
    )
    session.add(profile)
    session.commit()
    return session, user, project, profile


def _new_run(client: TestClient) -> tuple[Any, SqlUser, SqlGatewayProfile, UUID]:
    session, user, project, profile = _domain_setup(client)
    agent_session = create_agent_session(
        session,
        project_id=project.id,
        created_by_user_id=user.id,
        agent_kind=PlatformAgentKind.RESEARCHER,
    )
    _, run = append_user_message_and_queue_run(
        session,
        session_id=agent_session.id,
        requested_by_user_id=user.id,
        gateway_profile_id=profile.id,
        content_md="Explore the claim",
    )
    return session, user, profile, run.id


def test_agent_versions_are_pinned_trusted_and_digest_integral(client: TestClient) -> None:
    session, _, _, _ = _domain_setup(client)
    try:
        researcher = platform_agent_version(session, agent_kind=PlatformAgentKind.RESEARCHER)
        critic = platform_agent_version(session, agent_kind=PlatformAgentKind.CRITIC)
        assert researcher.id == RESEARCHER_VERSION_ID
        assert critic.id == CRITIC_VERSION_ID
        assert researcher.execution_profile.value == "TRUSTED_HOSTED"
        assert critic.execution_profile.value == "TRUSTED_HOSTED"
        for agent in (researcher, critic):
            assert agent.instructions_digest == sha256(agent.instructions_text.encode()).hexdigest()
    finally:
        session.close()


def test_custom_session_keeps_its_prompt_and_uses_it_for_model_input(client: TestClient) -> None:
    session, user, project, profile = _domain_setup(client)
    try:
        prompt = "Look for counterexamples before proposing a proof."
        created = create_agent_session(
            session,
            project_id=project.id,
            created_by_user_id=user.id,
            agent_kind=PlatformAgentKind.RESEARCHER,
            harness="codex",
            system_prompt=prompt,
        )
        _, run = append_user_message_and_queue_run(
            session,
            session_id=created.id,
            requested_by_user_id=user.id,
            gateway_profile_id=profile.id,
            content_md="Explore this statement.",
        )
        assert created.harness == "codex"
        assert created.system_prompt == prompt
        messages = model_messages(session, run)
        assert messages[0]["role"] == "system"
        assert messages[1] == {"role": "system", "content": prompt}
        assert messages[2] == {"role": "user", "content": "Explore this statement."}
    finally:
        session.close()


def test_custom_session_requires_a_harness_and_nonblank_prompt() -> None:
    base = {"project_id": "00000000-0000-0000-0000-000000000001", "agent_kind": "RESEARCHER"}
    for fields in (
        {"harness": "codex"},
        {"system_prompt": "custom"},
        {"harness": "codex", "system_prompt": "  "},
    ):
        with pytest.raises(ValueError):
            AgentSessionCreate.model_validate({**base, **fields})


def test_message_and_run_are_ordered_atomically_and_profile_is_snapshotted(
    client: TestClient,
) -> None:
    session, user, project, profile = _domain_setup(client)
    try:
        agent_session = create_agent_session(
            session,
            project_id=project.id,
            created_by_user_id=user.id,
            agent_kind=PlatformAgentKind.CRITIC,
        )
        message_one, run_one = append_user_message_and_queue_run(
            session,
            session_id=agent_session.id,
            requested_by_user_id=user.id,
            gateway_profile_id=profile.id,
            content_md="Check the first proof.",
        )
        message_two, run_two = append_user_message_and_queue_run(
            session,
            session_id=agent_session.id,
            requested_by_user_id=user.id,
            gateway_profile_id=profile.id,
            content_md="Now find a counterexample.",
        )
        assert (message_one.sequence, message_two.sequence) == (1, 2)
        assert (run_one.queue_sequence, run_two.queue_sequence) == (1, 2)
        assert run_one.request_message_id == message_one.id
        assert run_one.gateway_credential_version == 3
        assert run_one.gateway_model_id == "test-model"

        first_claim = claim_next_run(session, worker_id="worker-a", lease_for=timedelta(minutes=1))
        assert first_claim is not None and first_claim.id == run_one.id
        assert claim_next_run(session, worker_id="worker-b", lease_for=timedelta(minutes=1)) is None
        start_claimed_run(
            session,
            run_id=run_one.id,
            worker_id="worker-a",
            lease_generation=first_claim.lease_generation,
        )
        finish_run(
            session,
            run_id=run_one.id,
            worker_id="worker-a",
            lease_generation=first_claim.lease_generation,
            status=AgentRunStatus.COMPLETED,
            final_message_md="The proof needs a base case.",
        )
        next_claim = claim_next_run(session, worker_id="worker-b", lease_for=timedelta(minutes=1))
        assert next_claim is not None and next_claim.id == run_two.id
        messages = list(
            session.scalars(
                select(SqlAgentMessage)
                .where(SqlAgentMessage.session_id == agent_session.id)
                .order_by(SqlAgentMessage.sequence)
            )
        )
        assert [message.content_md for message in messages] == [
            "Check the first proof.",
            "Now find a counterexample.",
            "The proof needs a base case.",
        ]
    finally:
        session.close()


def test_transaction_compatible_claim_can_roll_back_without_leaking_a_lease(
    client: TestClient,
) -> None:
    session, _, _, run_id = _new_run(client)
    try:
        claimed = claim_next_run_in_transaction(
            session, worker_id="scheduler", lease_for=timedelta(minutes=1)
        )
        assert claimed is not None and claimed.id == run_id
        assert claimed.status is AgentRunStatus.CLAIMED
        session.rollback()
        persisted = session.get(SqlAgentRun, run_id)
        assert persisted is not None
        assert persisted.status is AgentRunStatus.QUEUED
        assert persisted.lease_owner is None
        assert persisted.lease_generation == 0
        assert persisted.attempt == 0
    finally:
        session.close()


def test_private_session_creator_must_match_the_run_requester(client: TestClient) -> None:
    session, owner, project, _ = _domain_setup(client)
    try:
        reader = SqlUser(
            issuer="https://issuer.example", subject="read-only-creator", email="r@test"
        )
        contributor = SqlUser(
            issuer="https://issuer.example", subject="contributor-requester", email="c@test"
        )
        session.add_all((reader, contributor))
        session.flush()
        profile = SqlGatewayProfile(
            user_id=contributor.id,
            display_name="contributor profile",
            base_url="https://models.example/v1",
            model_id="test-model",
            credential_version=1,
            encrypted_credential=b"ciphertext",
            wrapped_data_key=b"wrapped",
            encryption_key_version="test-key-v1",
        )
        session.add(profile)
        session.commit()
        private_session = create_agent_session(
            session,
            project_id=project.id,
            created_by_user_id=reader.id,
            agent_kind=PlatformAgentKind.RESEARCHER,
        )
        with pytest.raises(SessionStateError, match="private session creator"):
            append_user_message_and_queue_run(
                session,
                session_id=private_session.id,
                requested_by_user_id=contributor.id,
                gateway_profile_id=profile.id,
                content_md="Attempt to cross the private session boundary.",
            )
    finally:
        session.close()


def test_event_cursor_is_idempotent_and_stale_worker_generation_is_rejected(
    client: TestClient,
) -> None:
    session, _, _, run_id = _new_run(client)
    try:
        base = datetime(2026, 8, 21, tzinfo=UTC)
        claim = claim_next_run(
            session, worker_id="worker-a", lease_for=timedelta(seconds=10), now=base
        )
        assert claim is not None
        old_generation = claim.lease_generation
        start_claimed_run(
            session,
            run_id=run_id,
            worker_id="worker-a",
            lease_generation=old_generation,
            now=base,
        )
        usage = record_usage(
            session,
            run_id=run_id,
            worker_id="worker-a",
            lease_generation=old_generation,
            source=UsageSource.PROVIDER_REPORTED,
            input_tokens=4,
            output_tokens=2,
            total_tokens=6,
            idempotency_key="usage-1",
            now=base + timedelta(milliseconds=500),
        )
        replayed_usage = record_usage(
            session,
            run_id=run_id,
            worker_id="worker-a",
            lease_generation=old_generation,
            source=UsageSource.PROVIDER_REPORTED,
            input_tokens=4,
            output_tokens=2,
            total_tokens=6,
            idempotency_key="usage-1",
            now=base + timedelta(milliseconds=600),
        )
        assert replayed_usage.id == usage.id
        first = append_worker_event(
            session,
            run_id=run_id,
            worker_id="worker-a",
            lease_generation=old_generation,
            idempotency_key="chunk-1",
            kind=AgentRunEventKind.ASSISTANT_DELTA,
            payload={"text": "A"},
            now=base + timedelta(seconds=1),
        )
        duplicate = append_worker_event(
            session,
            run_id=run_id,
            worker_id="worker-a",
            lease_generation=old_generation,
            idempotency_key="chunk-1",
            kind=AgentRunEventKind.ASSISTANT_DELTA,
            payload={"text": "A"},
            now=base + timedelta(seconds=2),
        )
        assert (first.id, first.cursor, duplicate.cursor) == (duplicate.id, 3, 3)
        with pytest.raises(IdempotencyConflict):
            append_worker_event(
                session,
                run_id=run_id,
                worker_id="worker-a",
                lease_generation=old_generation,
                idempotency_key="chunk-1",
                kind=AgentRunEventKind.ASSISTANT_DELTA,
                payload={"text": "different"},
                now=base + timedelta(seconds=2),
            )
        requeue_expired_runs(session, max_attempts=2, now=base + timedelta(seconds=11))
        replacement = claim_next_run(
            session,
            worker_id="worker-b",
            lease_for=timedelta(seconds=10),
            now=base + timedelta(seconds=12),
        )
        assert replacement is not None and replacement.lease_generation == old_generation + 1
        with pytest.raises(LeaseLost):
            append_worker_event(
                session,
                run_id=run_id,
                worker_id="worker-a",
                lease_generation=old_generation,
                idempotency_key="stale",
                kind=AgentRunEventKind.ASSISTANT_DELTA,
                payload={"text": "late"},
                now=base + timedelta(seconds=12),
            )
        events = list(
            session.scalars(
                select(SqlAgentRunEvent)
                .where(SqlAgentRunEvent.run_id == run_id)
                .order_by(SqlAgentRunEvent.cursor)
            )
        )
        assert [event.cursor for event in events] == [1, 2, 3, 4]
        assert [event.kind for event in events] == [
            AgentRunEventKind.RUN_STARTED,
            AgentRunEventKind.USAGE_REPORTED,
            AgentRunEventKind.ASSISTANT_DELTA,
            AgentRunEventKind.RUNNER_LOST,
        ]
    finally:
        session.close()


def test_cancel_resume_and_runtime_bindings_preserve_history(client: TestClient) -> None:
    session, user, profile, run_id = _new_run(client)
    try:
        cancelled = request_cancel(session, run_id=run_id)
        assert cancelled.status is AgentRunStatus.CANCELLED
        successor = resume_run(
            session,
            run_id=run_id,
            requested_by_user_id=user.id,
            gateway_profile_id=profile.id,
        )
        assert successor.parent_run_id == run_id
        assert successor.status is AgentRunStatus.QUEUED
        original = session.get(type(cancelled), run_id)
        assert original is not None and original.status is AgentRunStatus.CANCELLED
        session_id = successor.session_id
        first_binding = activate_runtime_session_binding(
            session, session_id=session_id, adapter_name="builtin"
        )
        second_binding = activate_runtime_session_binding(
            session, session_id=session_id, adapter_name="builtin"
        )
        assert first_binding.status is RuntimeBindingStatus.SUPERSEDED
        assert second_binding.status is RuntimeBindingStatus.ACTIVE
        run_binding = create_runtime_run_binding(
            session,
            run_id=successor.id,
            session_binding_id=second_binding.id,
            adapter_name="builtin",
        )
        assert run_binding.session_id == session_id
        with pytest.raises(SessionStateError):
            create_runtime_run_binding(
                session,
                run_id=successor.id,
                session_binding_id=second_binding.id,
                adapter_name="builtin",
            )
    finally:
        session.close()


def test_postgresql_migration_compiles_runtime_integrity_and_immutable_history() -> None:
    api_directory = Path(__file__).resolve().parents[2] / "backend"
    sql = StringIO()
    config = Config(str(api_directory / "alembic.ini"), output_buffer=sql)
    config.set_main_option(
        "script_location", str(api_directory / "polycolab" / "db" / "migrations" / "postgresql")
    )
    config.set_main_option("sqlalchemy.url", "postgresql+psycopg://unused/unused")
    command.upgrade(config, "head", sql=True)
    compiled = " ".join(sql.getvalue().split())
    assert "fk_agent_runs_session_project" in compiled
    assert "fk_agent_runs_request_message_session" in compiled
    assert "fk_runtime_run_bindings_session_binding" in compiled
    assert "CREATE UNIQUE INDEX uq_runtime_session_bindings_active_session" in compiled
    assert "execution_profile IN ('TRUSTED_HOSTED')" in compiled
    assert "ALTER TABLE agent_sessions ADD COLUMN harness VARCHAR(32)" in compiled
    assert "ck_agent_sessions_custom_configuration" in compiled
    for table in (
        "platform_agent_versions",
        "agent_messages",
        "agent_run_events",
        "agent_run_usage",
    ):
        assert f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}" in compiled
