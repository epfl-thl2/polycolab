"""Shared scheduler persistence checks; no allocator or capacity evidence."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from test_sessions_store import _new_run

from polycolab.agents.sessions import claim_next_run_in_transaction
from polycolab.db.models import (
    SqlAgentRun,
    SqlExecutionClassState,
    SqlExecutionFairnessState,
    SqlExecutionSlotLease,
    SqlExecutionWorkItem,
)
from polycolab.entities.enums import (
    ExecutionTenantKind,
    ExecutionWorkloadClass,
)
from polycolab.entities.time import utc_now


def test_agent_work_item_and_slot_keep_physical_release_separate(
    client: TestClient,
) -> None:
    session, user, _, run_id = _new_run(client)
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None
        run.deadline_at = utc_now() + timedelta(minutes=5)
        session.commit()
        item = SqlExecutionWorkItem(
            agent_run_id=run.id,
            sponsor_user_id=user.id,
            project_id=run.project_id,
            workload_class=ExecutionWorkloadClass.AGENT,
            policy_version=1,
            reserved_cost=3,
            agent_model_tokens=100,
            agent_provider_cost_microusd=200,
            wall_seconds=300,
            queued_at=run.created_at,
        )
        session.add(item)
        session.add(
            SqlExecutionClassState(
                workload_class=ExecutionWorkloadClass.AGENT,
                active_policy_version=1,
            )
        )
        session.flush()
        session.add_all(
            [
                SqlExecutionFairnessState(
                    workload_class=ExecutionWorkloadClass.AGENT,
                    tenant_kind=ExecutionTenantKind.USER,
                    tenant_id=user.id,
                    policy_version=1,
                    virtual_runtime=0,
                ),
                SqlExecutionFairnessState(
                    workload_class=ExecutionWorkloadClass.AGENT,
                    tenant_kind=ExecutionTenantKind.PROJECT,
                    tenant_id=run.project_id,
                    policy_version=1,
                    virtual_runtime=0,
                ),
            ]
        )
        session.commit()

        claimed = claim_next_run_in_transaction(
            session, worker_id="scheduler", lease_for=timedelta(seconds=30)
        )
        assert claimed is not None and claimed.lease_expires_at is not None
        assert claimed.lease_acquired_at is not None
        assert claimed.deadline_at is not None
        slot = SqlExecutionSlotLease(
            work_item_id=item.id,
            workload_class=ExecutionWorkloadClass.AGENT,
            agent_run_id=claimed.id,
            generation=claimed.lease_generation,
            owner_id="scheduler",
            acquired_at=claimed.lease_acquired_at,
            lease_expires_at=claimed.lease_expires_at,
            safe_release_at=claimed.deadline_at,
        )
        session.add(slot)
        session.commit()

        slot.released_at = utc_now()
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        slot = session.get(SqlExecutionSlotLease, slot.id)
        assert slot is not None
        stopped = utc_now()
        slot.termination_confirmed_at = stopped
        slot.released_at = stopped - timedelta(microseconds=1)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        slot = session.get(SqlExecutionSlotLease, slot.id)
        assert slot is not None
        slot.termination_confirmed_at = stopped
        slot.released_at = stopped
        session.commit()

        impossible = SqlExecutionSlotLease(
            work_item_id=item.id,
            workload_class=ExecutionWorkloadClass.AGENT,
            agent_run_id=claimed.id,
            generation=claimed.lease_generation + 1,
            owner_id="scheduler",
            acquired_at=stopped,
            lease_expires_at=stopped - timedelta(seconds=1),
            safe_release_at=claimed.deadline_at,
        )
        session.add(impossible)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    finally:
        session.close()
