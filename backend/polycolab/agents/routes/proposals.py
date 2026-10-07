"""Member-only proposal review and exact run-context presentation for WP-10."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response, status
from sqlalchemy import select

from polycolab.access.actors import human_actor
from polycolab.access.authorization import (
    WorkspaceAction,
    WorkspaceNotFound,
    require_proposal_review,
    workspace_policy,
)
from polycolab.agents.context import manifest_artifacts, manifest_object_versions
from polycolab.agents.proposals import (
    BatchDecisionInput,
    ProposalInvalid,
    ProposalNotFound,
    accept_change,
    changes_for_proposal,
    decide_changes_atomically,
    proposal_in_project,
    reject_change,
)
from polycolab.agents.schemas import (
    ContextManifestRead,
    ProposalChangeAccept,
    ProposalChangeRead,
    ProposalChangeReject,
    ProposalDecisionBatchRequest,
    ProposalDetailRead,
    ProposalRead,
)
from polycolab.app.dependencies import CurrentUser, DbSession, Page, paginated
from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentSession,
    SqlContextManifest,
    SqlProposal,
    SqlProposalChange,
)
from polycolab.db.transaction import SqlAlchemyTransaction

router = APIRouter(prefix="/api/v1")


def _proposal_read(value: SqlProposal) -> ProposalRead:
    return ProposalRead(
        id=value.id,
        project_id=value.project_id,
        agent_version_id=value.agent_version_id,
        context_manifest_id=value.context_manifest_id,
        summary=value.summary,
        created_at=value.created_at,
    )


def _change_read(db: DbSession, value: SqlProposalChange) -> ProposalChangeRead:
    from polycolab.agents.proposal_projections import proposal_payload_read

    payload = proposal_payload_read(db, project_id=value.project_id, payload=value.payload)
    return ProposalChangeRead.model_validate(
        {
            **{field: getattr(value, field) for field in ProposalChangeRead.model_fields},
            "change_type": payload["kind"],
            "payload": payload,
        }
    )


def _manifest_read(db: DbSession, value: SqlContextManifest) -> ContextManifestRead:
    return ContextManifestRead(
        id=value.id,
        run_id=value.run_id,
        project_id=value.project_id,
        object_version_ids=[UUID(item) for item in value.revision_ids],
        artifact_ids=[item.id for item in manifest_artifacts(db, manifest=value)],
        digest=value.digest,
        created_at=value.created_at,
        object_versions=manifest_object_versions(db, manifest=value),
    )


def _review_scope(db: DbSession, *, proposal_id: UUID, user_id: UUID) -> SqlProposal:
    require_proposal_review(human_actor(user_id))
    value = db.get(SqlProposal, proposal_id)
    if value is None:
        raise WorkspaceNotFound
    workspace_policy.require_scope(
        SqlAlchemyTransaction(db), value.project_id, user_id, WorkspaceAction.REVIEW_PROPOSALS
    )
    return proposal_in_project(db, proposal_id=value.id, project_id=value.project_id)


def _private_manifest_scope(
    db: DbSession, *, proposal: SqlProposal, user_id: UUID
) -> SqlContextManifest:
    # Reviewing a proposal does not grant access to another member's private
    # chat or its attached context.  The requesting run owner may inspect it.
    if proposal.requested_by_user_id != user_id:
        raise WorkspaceNotFound
    workspace_policy.require_scope(
        SqlAlchemyTransaction(db), proposal.project_id, user_id, WorkspaceAction.RUN_AGENTS
    )
    run = db.get(SqlAgentRun, proposal.run_id)
    parent = db.get(SqlAgentSession, proposal.session_id)
    manifest = db.get(SqlContextManifest, proposal.context_manifest_id)
    if (
        run is None
        or parent is None
        or manifest is None
        or parent.created_by_user_id != user_id
        or run.requested_by_user_id != user_id
        or manifest.run_id != run.id
    ):
        raise WorkspaceNotFound
    return manifest


def _private_run_manifest_scope(
    db: DbSession, *, run_id: UUID, user_id: UUID
) -> SqlContextManifest:
    run = db.get(SqlAgentRun, run_id)
    if run is None or run.requested_by_user_id != user_id:
        raise WorkspaceNotFound
    workspace_policy.require_scope(
        SqlAlchemyTransaction(db), run.project_id, user_id, WorkspaceAction.RUN_AGENTS
    )
    parent = db.get(SqlAgentSession, run.session_id)
    manifest = db.scalar(select(SqlContextManifest).where(SqlContextManifest.run_id == run.id))
    if parent is None or manifest is None or parent.created_by_user_id != user_id:
        raise WorkspaceNotFound
    return manifest


@router.get(
    "/agent-runs/{run_id}/context",
    response_model=ContextManifestRead,
    operation_id="getAgentRunContextManifest",
    tags=["agent-runs"],
)
def get_agent_run_context(run_id: UUID, db: DbSession, user: CurrentUser) -> ContextManifestRead:
    return _manifest_read(db, _private_run_manifest_scope(db, run_id=run_id, user_id=user.id))


@router.get(
    "/workspaces/{workspace_id}/proposals",
    response_model=list[ProposalRead],
    operation_id="listWorkspaceProposals",
    tags=["proposals"],
)
def list_project_proposals(
    workspace_id: UUID, response: Response, page: Page, db: DbSession, user: CurrentUser
) -> list[ProposalRead]:
    workspace_policy.require_scope(
        SqlAlchemyTransaction(db), workspace_id, user.id, WorkspaceAction.REVIEW_PROPOSALS
    )
    values = list(
        db.scalars(
            select(SqlProposal)
            .where(SqlProposal.project_id == workspace_id)
            .order_by(SqlProposal.created_at.desc(), SqlProposal.id.desc())
        )
    )
    return paginated([_proposal_read(item) for item in values], page, response)


@router.get(
    "/proposals/{proposal_id}",
    response_model=ProposalDetailRead,
    operation_id="getProposal",
    tags=["proposals"],
)
def get_proposal(proposal_id: UUID, db: DbSession, user: CurrentUser) -> ProposalDetailRead:
    value = _review_scope(db, proposal_id=proposal_id, user_id=user.id)
    return ProposalDetailRead(
        **_proposal_read(value).model_dump(),
        changes=[_change_read(db, item) for item in changes_for_proposal(db, proposal_id=value.id)],
    )


@router.get(
    "/proposals/{proposal_id}/context",
    response_model=ContextManifestRead,
    operation_id="getProposalContextManifest",
    tags=["proposals"],
)
def get_proposal_context(
    proposal_id: UUID, db: DbSession, user: CurrentUser
) -> ContextManifestRead:
    proposal = _review_scope(db, proposal_id=proposal_id, user_id=user.id)
    return _manifest_read(db, _private_manifest_scope(db, proposal=proposal, user_id=user.id))


@router.post(
    "/proposals/{proposal_id}/changes/{change_id}/accept",
    response_model=ProposalChangeRead,
    operation_id="acceptProposalChange",
    tags=["proposals"],
)
def post_accept_proposal_change(
    proposal_id: UUID,
    change_id: UUID,
    payload: ProposalChangeAccept,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
    db: DbSession,
    user: CurrentUser,
) -> ProposalChangeRead:
    proposal = _review_scope(db, proposal_id=proposal_id, user_id=user.id)
    try:
        return _change_read(
            db,
            accept_change(
                db,
                proposal=proposal,
                change_id=change_id,
                decider=user,
                idempotency_key=idempotency_key,
                edited_payload=payload.payload.model_dump(mode="json")
                if payload.payload is not None
                else None,
            ),
        )
    except ProposalInvalid:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from None
    except ProposalNotFound:
        raise WorkspaceNotFound from None


@router.post(
    "/proposals/{proposal_id}/changes/{change_id}/reject",
    response_model=ProposalChangeRead,
    operation_id="rejectProposalChange",
    tags=["proposals"],
)
def post_reject_proposal_change(
    proposal_id: UUID,
    change_id: UUID,
    payload: ProposalChangeReject,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
    db: DbSession,
    user: CurrentUser,
) -> ProposalChangeRead:
    proposal = _review_scope(db, proposal_id=proposal_id, user_id=user.id)
    try:
        return _change_read(
            db,
            reject_change(
                db,
                proposal=proposal,
                change_id=change_id,
                decider=user,
                idempotency_key=idempotency_key,
                reason=payload.reason,
            ),
        )
    except ProposalNotFound:
        raise WorkspaceNotFound from None


@router.post(
    "/proposals/{proposal_id}/decisions",
    response_model=list[ProposalChangeRead],
    operation_id="decideProposalChangesAtomically",
    tags=["proposals"],
)
def post_proposal_decisions(
    proposal_id: UUID,
    payload: ProposalDecisionBatchRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
    db: DbSession,
    user: CurrentUser,
) -> list[ProposalChangeRead]:
    proposal = _review_scope(db, proposal_id=proposal_id, user_id=user.id)
    try:
        return [
            _change_read(db, item)
            for item in decide_changes_atomically(
                db,
                proposal=proposal,
                decider=user,
                idempotency_key=idempotency_key,
                decisions=[
                    BatchDecisionInput(
                        change_id=item.change_id,
                        action=item.action,
                        payload=item.payload.model_dump(mode="json")
                        if item.payload is not None
                        else None,
                        reason=item.reason,
                    )
                    for item in payload.decisions
                ],
            )
        ]
    except ProposalInvalid:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from None
    except ProposalNotFound:
        raise WorkspaceNotFound from None
