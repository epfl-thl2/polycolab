"""Dedicated agent adapters, dormant until Research explicitly grants these tools.

Existing record-edit grants do not issue computation capabilities. Integration
must add an explicit human-approved computation grant before adding these names
to capability issuance. No fallback from write_record or sponsor identity exists.
"""

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from polycolab.access.authorization import AuthorizationDenied
from polycolab.agents import grants as run_grants
from polycolab.agents.context import manifest_artifacts, run_artifacts
from polycolab.agents.tools import authorize_tool
from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentRunEvent,
    SqlContextManifest,
    SqlContributionEnvelope,
    SqlRunRevisionOutput,
    SqlRunToolCapability,
)
from polycolab.entities.enums import AgentRunEventKind, ContributionActorKind
from polycolab.platform.config import Settings
from polycolab.research.direct_contributions import fence
from polycolab.verification.contracts import JobRead, JobSubmission

TOOL_NAMES = frozenset({"submit_verification", "inspect_verification", "cancel_verification"})


@dataclass(frozen=True)
class AgentAuthority:
    run: SqlAgentRun
    capability: SqlRunToolCapability
    manifest: SqlContextManifest
    readable: frozenset[UUID]
    readable_artifacts: frozenset[UUID]
    max_mutations: int

    def fence(self, session: Session) -> None:
        fence(session, self.run, self.capability)

    def check_submission(self, payload: JobSubmission) -> None:
        targets = {payload.work_target_revision_id}
        if payload.research_attempt_revision_id:
            targets.add(payload.research_attempt_revision_id)
        for item in payload.inputs:
            if item.revision_id is not None:
                targets.add(item.revision_id)
            elif item.artifact_id not in self.readable_artifacts:
                raise AuthorizationDenied("artifact input is not in the agent manifest")
        if payload.project_id != self.run.project_id or not targets <= self.readable:
            raise AuthorizationDenied("verification input outside current run scope")

    def verify_invocation(
        self,
        session: Session,
        invocation: str,
        source_cursor: int | None,
        *,
        tool_name: str,
    ) -> int:
        if source_cursor is None:
            raise AuthorizationDenied("missing verification invocation provenance")
        event = session.scalar(
            select(SqlAgentRunEvent).where(
                SqlAgentRunEvent.run_id == self.run.id,
                SqlAgentRunEvent.cursor == source_cursor,
            )
        )
        if (
            event is None
            or event.kind != AgentRunEventKind.TOOL_REQUESTED
            or event.payload.get("tool_name") != tool_name
            or event.idempotency_key != f"{invocation}-requested"
        ):
            raise AuthorizationDenied("untrusted verification invocation provenance")
        return source_cursor

    def contribution(
        self, session: Session, scope_id: UUID, *, source_cursor: int
    ) -> SqlContributionEnvelope:
        used = (
            session.scalar(
                select(func.count())
                .select_from(SqlContributionEnvelope)
                .where(SqlContributionEnvelope.run_id == self.run.id)
            )
            or 0
        )
        if used >= self.max_mutations:
            raise AuthorizationDenied("run mutation budget exhausted")
        envelope = SqlContributionEnvelope(
            project_id=self.run.project_id,
            actor_kind=ContributionActorKind.AGENT,
            sponsor_user_id=self.run.requested_by_user_id,
            agent_version_id=self.run.agent_version_id,
            run_id=self.run.id,
            session_id=self.run.session_id,
            context_manifest_id=self.manifest.id,
            ownership_scope_id=scope_id,
            operation="verification.submit",
            source_event_cursors=[source_cursor],
        )
        session.add(envelope)
        session.flush()
        return envelope


def authorize(
    session: Session, *, token: str, name: str, user_id: UUID, project_id: UUID
) -> AgentAuthority:
    if name not in TOOL_NAMES:
        raise AuthorizationDenied("unknown verification tool")
    capability, run, manifest = authorize_tool(session, token=token, tool_name=name)
    grant = run_grants.requested(session, run.id)
    if (
        run.requested_by_user_id != user_id
        or run.project_id != project_id
        or grant is None
        or grant.destination != "WORKSPACE"
        or "RUN_VERIFICATION" not in grant.allowed_operations
    ):
        raise AuthorizationDenied("verification destination not granted")
    run_grants.validate(
        session,
        project_id=project_id,
        user_id=user_id,
        agent_version_id=run.agent_version_id,
        context_ids=[UUID(value) for value in manifest.revision_ids],
        authority=grant,
    )
    readable = {UUID(value) for value in manifest.revision_ids}
    readable.update(
        session.scalars(
            select(SqlRunRevisionOutput.revision_id).where(SqlRunRevisionOutput.run_id == run.id)
        )
    )
    artifacts = frozenset(
        row.id
        for row in (
            *manifest_artifacts(session, manifest=manifest),
            *run_artifacts(session, run=run),
        )
    )
    return AgentAuthority(
        run,
        capability,
        manifest,
        frozenset(readable),
        artifacts,
        grant.max_mutations,
    )


def execute(
    session: Session,
    *,
    token: str,
    name: str,
    project_id: UUID,
    settings: Settings,
    submission: JobSubmission | None = None,
    retry_key: str | None = None,
    job_id: UUID | None = None,
    invocation_key: str | None = None,
    source_event_cursor: int | None = None,
) -> JobRead:
    from polycolab.verification import service as verification

    # Untrusted candidate lookup chooses the sponsor only. Every operation below
    # reauthorizes the capability under project/scope locks in its own transaction.
    if not token or len(token) > 256:
        raise AuthorizationDenied("invalid verification capability")
    candidate = session.scalar(
        select(SqlRunToolCapability).where(
            SqlRunToolCapability.token_digest == hashlib.sha256(token.encode()).hexdigest()
        )
    )
    if candidate is None:
        raise AuthorizationDenied("invalid verification capability")
    user_id = candidate.user_id
    session.rollback()
    if name == "submit_verification" and submission is not None and retry_key is not None:
        if submission.project_id != project_id:
            raise AuthorizationDenied("verification destination not granted")
        return verification.submit(
            session,
            user_id=user_id,
            submission=submission,
            retry_key=retry_key,
            settings=settings,
            agent_token=token,
            source_event_cursor=source_event_cursor,
        )
    if name == "inspect_verification" and job_id is not None:
        return verification.inspect(
            session, user_id=user_id, project_id=project_id, job_id=job_id, agent_token=token
        )
    if name == "cancel_verification" and job_id is not None:
        return verification.cancel(
            session,
            user_id=user_id,
            project_id=project_id,
            job_id=job_id,
            agent_token=token,
            invocation_key=invocation_key,
            source_event_cursor=source_event_cursor,
        )
    raise AuthorizationDenied("invalid verification tool arguments")
