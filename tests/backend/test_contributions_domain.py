from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

import polycolab.research.contributions as contribution_domain
from polycolab.access.actors import ActorOperation, agent_actor, human_actor
from polycolab.access.authorization import AuthorizationDenied, ProjectNotFound
from polycolab.db.models import (
    SqlContributionEntityLink,
    SqlContributionEnvelope,
    SqlMutationReceipt,
    SqlObjectRevision,
    SqlOutboxEvent,
    SqlResearchObject,
    SqlResearchScope,
    SqlUser,
)
from polycolab.entities.enums import ResearchObjectKind
from polycolab.research.contributions import (
    ContributionConflict,
    ContributionOutput,
    record_contribution,
)
from polycolab.research.objects import create_object


def _project_and_scope(client: TestClient) -> tuple[Any, SqlUser, SqlResearchScope]:
    response = client.post(
        "/api/v1/projects",
        headers={"Authorization": "Bearer owner"},
        json={"name": "Contribution test", "visibility": "PRIVATE"},
    )
    assert response.status_code == 201
    project_id = UUID(response.json()["id"])
    app = cast(Any, client.app)
    session = app.state.session_factory()
    user = session.scalar(select(SqlUser).where(SqlUser.subject == "owner"))
    scope = session.scalar(
        select(SqlResearchScope).where(SqlResearchScope.project_id == project_id)
    )
    assert user is not None and scope is not None
    return session, user, scope


def test_retry_returns_same_resources_and_changed_payload_conflicts(client: TestClient) -> None:
    session, user, scope = _project_and_scope(client)
    try:
        actor = human_actor(user.id)
        calls = []

        def create_output(envelope: SqlContributionEnvelope) -> list[ContributionOutput]:
            assert scope.project_id is not None
            calls.append(True)
            _, revision = create_object(
                session,
                project_id=scope.project_id,
                author=user,
                kind=ResearchObjectKind.CLAIM,
                title="note",
                content_md="one",
                rationale=None,
                commit=False,
                contribution=envelope,
            )
            return [ContributionOutput("OBJECT_REVISION", revision.id, scope.id)]

        first = record_contribution(
            session,
            actor=actor,
            operation="record_note",
            idempotency_key="note-1",
            request_payload={"body": "one"},
            create_outputs=create_output,
            ownership_scope_id=scope.id,
        )
        retry = record_contribution(
            session,
            actor=actor,
            operation="record_note",
            idempotency_key="note-1",
            request_payload={"body": "one"},
            create_outputs=create_output,
            ownership_scope_id=scope.id,
        )
        assert retry.replayed
        assert len(calls) == 1
        assert retry.envelope.id == first.envelope.id
        assert [link.id for link in retry.links] == [link.id for link in first.links]
        with pytest.raises(ContributionConflict):
            record_contribution(
                session,
                actor=actor,
                operation="record_note",
                idempotency_key="note-1",
                request_payload={"body": "changed"},
                create_outputs=create_output,
                ownership_scope_id=scope.id,
            )
        assert session.scalar(select(func.count()).select_from(SqlContributionEnvelope)) == 1
        assert session.scalar(select(func.count()).select_from(SqlContributionEntityLink)) == 2
        assert session.scalar(select(func.count()).select_from(SqlMutationReceipt)) == 1
        assert session.scalar(select(func.count()).select_from(SqlOutboxEvent)) == 3
    finally:
        session.close()


def test_replay_preserves_multiple_output_order(client: TestClient) -> None:
    session, user, scope = _project_and_scope(client)

    next_id = 100

    def assign_reverse_ids(*_: object) -> None:
        nonlocal next_id
        links = [item for item in session.new if isinstance(item, SqlContributionEntityLink)]
        for link in links:
            link.id = UUID(int=next_id)
            next_id -= 1

    event.listen(session, "before_flush", assign_reverse_ids)
    with session:

        def create_outputs(envelope: SqlContributionEnvelope) -> list[ContributionOutput]:
            assert scope.project_id is not None
            research_object, revision = create_object(
                session,
                project_id=scope.project_id,
                author=user,
                kind=ResearchObjectKind.CLAIM,
                title="Two outputs",
                content_md="content",
                rationale=None,
                commit=False,
                contribution=envelope,
            )
            return [
                ContributionOutput("RESEARCH_OBJECT", research_object.id, scope.id),
                ContributionOutput("OBJECT_REVISION", revision.id, scope.id),
            ]

        first = record_contribution(
            session,
            actor=human_actor(user.id),
            operation="create",
            idempotency_key="ordered",
            request_payload={},
            ownership_scope_id=scope.id,
            create_outputs=create_outputs,
        )
        event.remove(session, "before_flush", assign_reverse_ids)
        retry = record_contribution(
            session,
            actor=human_actor(user.id),
            operation="create",
            idempotency_key="ordered",
            request_payload={},
            ownership_scope_id=scope.id,
            create_outputs=create_outputs,
        )
        assert [link.id for link in first.links] == [UUID(int=99), UUID(int=100)]
        assert [link.id for link in retry.links] == [link.id for link in first.links]


def test_duplicate_outputs_roll_back_and_allow_corrected_retry(client: TestClient) -> None:
    session, user, scope = _project_and_scope(client)
    with session:
        duplicate = True

        def create_outputs(envelope: SqlContributionEnvelope) -> list[ContributionOutput]:
            assert scope.project_id is not None
            _, revision = create_object(
                session,
                project_id=scope.project_id,
                author=user,
                kind=ResearchObjectKind.CLAIM,
                title="Duplicate output",
                content_md="content",
                rationale=None,
                commit=False,
                contribution=envelope,
            )
            output = ContributionOutput("OBJECT_REVISION", revision.id, scope.id)
            return [output, output] if duplicate else [output]

        def record() -> contribution_domain.ContributionMutation:
            return record_contribution(
                session,
                actor=human_actor(user.id),
                operation="create",
                idempotency_key="duplicate",
                request_payload={},
                ownership_scope_id=scope.id,
                create_outputs=create_outputs,
            )

        with pytest.raises(ContributionConflict):
            record()
        for model in (
            SqlResearchObject,
            SqlObjectRevision,
            SqlContributionEnvelope,
            SqlContributionEntityLink,
            SqlMutationReceipt,
            SqlOutboxEvent,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0

        duplicate = False
        first = record()
        retry = record()
        assert retry.replayed
        assert retry.receipt.id == first.receipt.id
        assert [link.id for link in retry.links] == [link.id for link in first.links]


def test_forced_outbox_failure_rolls_back_content_provenance_and_receipt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, user, scope = _project_and_scope(client)
    try:

        def fail_append(*args: object, **kwargs: object) -> None:
            raise RuntimeError("forced outbox failure")

        monkeypatch.setattr(contribution_domain, "append_event", fail_append)

        def create_output(envelope: SqlContributionEnvelope) -> list[ContributionOutput]:
            assert scope.project_id is not None
            _, revision = create_object(
                session,
                project_id=scope.project_id,
                author=user,
                kind=ResearchObjectKind.CLAIM,
                title="note",
                content_md="rollback",
                rationale=None,
                commit=False,
                contribution=envelope,
            )
            return [ContributionOutput("OBJECT_REVISION", revision.id, scope.id)]

        with pytest.raises(RuntimeError, match="forced outbox failure"):
            record_contribution(
                session,
                actor=human_actor(user.id),
                operation="record_note",
                idempotency_key="note-failure",
                request_payload={"body": "must roll back"},
                create_outputs=create_output,
                ownership_scope_id=scope.id,
            )
        assert session.scalar(select(func.count()).select_from(SqlContributionEnvelope)) == 0
        assert session.scalar(select(func.count()).select_from(SqlContributionEntityLink)) == 0
        assert session.scalar(select(func.count()).select_from(SqlMutationReceipt)) == 0
        assert session.scalar(select(func.count()).select_from(SqlOutboxEvent)) == 0
        assert session.scalar(select(func.count()).select_from(SqlResearchObject)) == 0
        assert session.scalar(select(func.count()).select_from(SqlObjectRevision)) == 0
    finally:
        session.close()


def test_agent_envelopes_include_validated_run_and_context_references() -> None:
    actor = agent_actor(
        sponsor_user_id=uuid4(),
        agent_version_id=uuid4(),
        run_id=uuid4(),
        capability_id=uuid4(),
        session_id=uuid4(),
        context_manifest_id=uuid4(),
        project_id=uuid4(),
        operation_scope=frozenset({ActorOperation.CONTRIBUTION_CREATE}),
    )
    values = contribution_domain._envelope_values(actor)
    assert values["run_id"] == actor.run_id
    assert values["session_id"] == actor.session_id
    assert values["context_manifest_id"] == actor.context_manifest_id


def test_nonexistent_output_and_wrong_scope_are_rejected(client: TestClient) -> None:
    session, user, scope = _project_and_scope(client)
    with session:
        with pytest.raises(ContributionConflict):
            record_contribution(
                session,
                actor=human_actor(user.id),
                operation="record",
                idempotency_key="missing",
                request_payload={},
                ownership_scope_id=scope.id,
                outputs=[ContributionOutput("OBJECT_REVISION", uuid4(), scope.id)],
            )
        assert session.scalar(select(func.count()).select_from(SqlContributionEnvelope)) == 0


def test_contribution_composition_rechecks_membership_and_archive(client: TestClient) -> None:
    session, user, scope = _project_and_scope(client)
    outsider = client.get("/api/v1/users/me", headers={"Authorization": "Bearer outsider"}).json()
    with session:
        with pytest.raises(ProjectNotFound):
            record_contribution(
                session,
                actor=human_actor(UUID(outsider["id"])),
                operation="record",
                idempotency_key="unauthorized",
                request_payload={},
                ownership_scope_id=scope.id,
                outputs=[ContributionOutput("OBJECT_REVISION", uuid4(), scope.id)],
            )
        session.rollback()
        client.patch(
            f"/api/v1/projects/{scope.project_id}",
            headers={"Authorization": "Bearer owner"},
            json={"archived": True},
        )
        with pytest.raises(AuthorizationDenied):
            record_contribution(
                session,
                actor=human_actor(user.id),
                operation="record",
                idempotency_key="archived",
                request_payload={},
                ownership_scope_id=scope.id,
                outputs=[ContributionOutput("OBJECT_REVISION", uuid4(), scope.id)],
            )
