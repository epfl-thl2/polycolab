"""Narrow WP-10 tool-capability issue and verification boundary."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor, ActorOperation, agent_actor
from polycolab.access.authorization import (
    ROLE_ACTIONS,
    AuthorizationDenied,
    WorkspaceAction,
    lock_workspace_authorization,
    require_proposal_submission,
    workspace_policy,
)
from polycolab.agents import grants as run_grants
from polycolab.agents.context import (
    ContextInvalid,
    manifest_artifacts,
    manifest_revisions,
    run_artifacts,
)
from polycolab.agents.proposal_version_schemas import ObjectVersionProposalSubmit
from polycolab.agents.proposals import ProposalInvalid, submit_proposal
from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentSession,
    SqlContextManifest,
    SqlObjectRevision,
    SqlRelationAssertion,
    SqlRunRevisionOutput,
    SqlRunToolCapability,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import AgentRunStatus, AgentSessionStatus
from polycolab.entities.time import utc_now
from polycolab.platform.config import Settings
from polycolab.research.activity_schemas import (
    AgentObjectVersionProgress,
    AgentSummaryVersionWrite,
    ResearchSummaryVersionRead,
)
from polycolab.research.contracts import (
    RecordWrite,
    ResearchCommentToolWrite,
    ResearchProgressToolWrite,
    ResearchSummaryToolWrite,
    ScopedRelationWrite,
)
from polycolab.research.records import accessible_revision, relation_read_condition
from polycolab.research.review_schemas import AgentReviewWrite
from polycolab.research.version_commands import agent_snapshot_command, declaration_command
from polycolab.research.version_projections import relationship_reads, version_reads
from polycolab.research.version_schemas import (
    AgentObjectVersionComment,
    AgentObjectVersionWrite,
    AgentRelationshipWrite,
    VersionLibraryDestination,
)
from polycolab.verification.contracts import VerificationJobReference
from polycolab.verification.version_contracts import VersionJobRead, VersionJobSubmission

TOOL_NAMES = frozenset({"get_context", "get_object_version", "get_dependencies", "submit_proposal"})
DIRECT_TOOL_NAMES = frozenset(
    {
        "write_object_version",
        "create_relation",
        "write_summary",
        "comment_on_object_version",
        "report_progress",
        "review_object_version",
    }
)
VERIFICATION_TOOL_NAMES = frozenset(
    {"submit_verification", "inspect_verification", "cancel_verification"}
)
ALL_TOOL_NAMES = TOOL_NAMES | DIRECT_TOOL_NAMES | VERIFICATION_TOOL_NAMES


def allowed_tools(session: Session, run: SqlAgentRun) -> frozenset[str]:
    authority = run_grants.requested(session, run.id)
    names = set(TOOL_NAMES)
    if authority is not None:
        if {"CREATE_RECORD", "REVISE_RECORD"} & set(authority.allowed_operations):
            names.add("write_object_version")
        if "CREATE_RELATION" in authority.allowed_operations:
            names.add("create_relation")
        if "WRITE_SUMMARY" in authority.allowed_operations:
            names.add("write_summary")
        if "COMMENT" in authority.allowed_operations:
            names.add("comment_on_object_version")
        if "REVIEW_RESEARCH" in authority.allowed_operations:
            names.add("review_object_version")
        if "REPORT_PROGRESS" in authority.allowed_operations:
            names.add("report_progress")
        if "RUN_VERIFICATION" in authority.allowed_operations:
            names.update(VERIFICATION_TOOL_NAMES)
    return frozenset(names)


def definitions(session: Session, run: SqlAgentRun) -> list[dict[str, object]]:
    values = list(PLATFORM_TOOL_DEFINITIONS)
    names = allowed_tools(session, run)
    schemas = (
        ("write_object_version", AgentObjectVersionWrite),
        ("create_relation", AgentRelationshipWrite),
        ("write_summary", AgentSummaryVersionWrite),
        ("comment_on_object_version", AgentObjectVersionComment),
        ("report_progress", AgentObjectVersionProgress),
        ("review_object_version", AgentReviewWrite),
        ("submit_verification", VersionJobSubmission),
        ("inspect_verification", VerificationJobReference),
        ("cancel_verification", VerificationJobReference),
    )
    for name, schema in schemas:
        if name in names:
            values.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": (
                            "Save research under the explicit run grant. "
                            "Unauthorized edits require a suggestion."
                        ),
                        "parameters": schema.model_json_schema(),
                    },
                }
            )
    return values


# These are platform-owned input contracts.  They are sent to the provider only
# by the private model gateway; callers never choose tools or their schemas.
PLATFORM_TOOL_DEFINITIONS: tuple[dict[str, object], ...] = (
    {
        "type": "function",
        "function": {
            "name": "get_context",
            "description": "Read the run's pinned research context.",
            "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_object_version",
            "description": "Read one immutable object version from the pinned context.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["object_version_id"],
                "properties": {"object_version_id": {"type": "string", "format": "uuid"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dependencies",
            "description": "Read visible relationships between pinned object versions.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["object_version_id"],
                "properties": {"object_version_id": {"type": "string", "format": "uuid"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_proposal",
            "description": "Submit structured proposed research changes for human review.",
            "parameters": ObjectVersionProposalSubmit.model_json_schema(),
        },
    },
)


class ToolCapabilityInvalid(Exception):
    pass


def _object_version_argument(arguments: dict[str, object]) -> str:
    if set(arguments) != {"object_version_id"}:
        raise ToolCapabilityInvalid
    value = arguments["object_version_id"]
    if not isinstance(value, str) or len(value) > 64:
        raise ToolCapabilityInvalid
    try:
        UUID(value)
    except ValueError as exc:
        raise ToolCapabilityInvalid from exc
    return value


def _validated_tool_arguments(name: str, arguments: dict[str, object]) -> None:
    if name == "get_context":
        if arguments:
            raise ToolCapabilityInvalid
        return
    if name in {"get_object_version", "get_dependencies"}:
        _object_version_argument(arguments)
        return
    if name == "submit_proposal":
        try:
            payload = ObjectVersionProposalSubmit.model_validate(arguments)
        except ValueError as exc:
            raise ToolCapabilityInvalid from exc
        if not payload.summary.strip():
            raise ToolCapabilityInvalid
        return
    raise ToolCapabilityInvalid


def _expired(value: datetime) -> bool:
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized <= utc_now()


def issue_tool_capability(
    session: Session,
    *,
    run: SqlAgentRun,
    manifest: SqlContextManifest,
    ttl_seconds: int,
    lease_generation: int | None = None,
) -> str:
    lease_generation = run.lease_generation if lease_generation is None else lease_generation
    parent = session.get(SqlAgentSession, run.session_id)
    if ttl_seconds < 1 or ttl_seconds > 300:
        raise ToolCapabilityInvalid
    if (
        run.session_id is None
        or parent is None
        or parent.created_by_user_id != run.requested_by_user_id
        or manifest.run_id != run.id
        or manifest.project_id != run.project_id
        or manifest.requested_by_user_id != run.requested_by_user_id
        or manifest.agent_version_id != run.agent_version_id
        or run.status is not AgentRunStatus.RUNNING
        or run.lease_generation != lease_generation
        or run.lease_owner is None
        or run.lease_expires_at is None
        or _expired(run.lease_expires_at)
        or not workspace_policy.can(
            SqlAlchemyTransaction(session),
            run.project_id,
            run.requested_by_user_id,
            WorkspaceAction.RUN_AGENTS,
        )
    ):
        raise ToolCapabilityInvalid
    for prior in session.scalars(
        select(SqlRunToolCapability).where(
            SqlRunToolCapability.run_id == run.id, SqlRunToolCapability.revoked.is_(False)
        )
    ):
        prior.revoked = True
    token = secrets.token_urlsafe(32)
    session.add(
        SqlRunToolCapability(
            token_digest=hashlib.sha256(token.encode()).hexdigest(),
            run_id=run.id,
            session_id=run.session_id,
            project_id=run.project_id,
            user_id=run.requested_by_user_id,
            agent_version_id=run.agent_version_id,
            context_manifest_id=manifest.id,
            allowed_tools=sorted(allowed_tools(session, run)),
            lease_generation=lease_generation,
            expires_at=utc_now() + timedelta(seconds=ttl_seconds),
        )
    )
    session.commit()
    return token


def _locked_current_scope(
    session: Session, *, project_id: UUID, user_id: UUID, action: WorkspaceAction
) -> bool:
    project, membership = lock_workspace_authorization(
        SqlAlchemyTransaction(session), project_id=project_id, user_id=user_id
    )
    return (
        project is not None
        and project.deleted_at is None
        and project.archived_at is None
        and membership is not None
        and action in ROLE_ACTIONS[membership.role]
    )


def authorize_tool(
    session: Session, *, token: str, tool_name: str
) -> tuple[SqlRunToolCapability, SqlAgentRun, SqlContextManifest]:
    if (
        not token
        or len(token) > 256
        or any(ord(value) < 32 or ord(value) == 127 for value in token)
    ):
        raise ToolCapabilityInvalid
    digest = hashlib.sha256(token.encode()).hexdigest()
    candidate = session.scalar(
        select(SqlRunToolCapability).where(SqlRunToolCapability.token_digest == digest)
    )
    if candidate is None:
        raise ToolCapabilityInvalid
    # Match project mutation ordering before taking runtime/capability locks.
    lock_workspace_authorization(
        SqlAlchemyTransaction(session), project_id=candidate.project_id, user_id=candidate.user_id
    )
    if tool_name in DIRECT_TOOL_NAMES:
        from polycolab.catalogue.admission import lock_commons

        lock_commons(session)
    parent = session.scalar(
        select(SqlAgentSession)
        .where(SqlAgentSession.id == candidate.session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    run = session.scalar(
        select(SqlAgentRun)
        .where(SqlAgentRun.id == candidate.run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    capability = session.scalar(
        select(SqlRunToolCapability)
        .where(SqlRunToolCapability.token_digest == digest)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        capability is None
        or capability.revoked
        or _expired(capability.expires_at)
        or tool_name not in capability.allowed_tools
    ):
        raise ToolCapabilityInvalid
    manifest = session.scalar(
        select(SqlContextManifest)
        .where(SqlContextManifest.id == capability.context_manifest_id)
        .with_for_update()
    )
    if (
        run is None
        or parent is None
        or manifest is None
        or run.id != capability.run_id
        or run.session_id != capability.session_id
        or run.project_id != capability.project_id
        or run.agent_version_id != capability.agent_version_id
        or run.requested_by_user_id != capability.user_id
        or parent.created_by_user_id != run.requested_by_user_id
        or parent.created_by_user_id != capability.user_id
        or parent.project_id != run.project_id
        or parent.agent_version_id != run.agent_version_id
        or run.status is not AgentRunStatus.RUNNING
        or run.lease_generation != capability.lease_generation
        or run.lease_owner is None
        or run.lease_expires_at is None
        or _expired(run.lease_expires_at)
        or parent.status is not AgentSessionStatus.ACTIVE
        or manifest.run_id != run.id
        or manifest.project_id != run.project_id
        or manifest.requested_by_user_id != run.requested_by_user_id
        or manifest.agent_version_id != run.agent_version_id
        or not _locked_current_scope(
            session,
            project_id=run.project_id,
            user_id=run.requested_by_user_id,
            action=WorkspaceAction.RUN_AGENTS,
        )
        or not _locked_current_scope(
            session,
            project_id=run.project_id,
            user_id=parent.created_by_user_id,
            action=WorkspaceAction.VIEW,
        )
    ):
        raise ToolCapabilityInvalid
    return capability, run, manifest


def _actor_for_validated_tool(
    capability: SqlRunToolCapability, *, run: SqlAgentRun, tool_name: str
) -> Actor:
    operation_scope = (
        frozenset({ActorOperation.PROPOSAL_SUBMISSION})
        if tool_name == "submit_proposal"
        else frozenset()
    )
    return agent_actor(
        sponsor_user_id=capability.user_id,
        agent_version_id=capability.agent_version_id,
        run_id=run.id,
        capability_id=capability.id,
        session_id=run.session_id,
        context_manifest_id=capability.context_manifest_id,
        project_id=capability.project_id,
        operation_scope=operation_scope,
    )


def execute_tool(
    session: Session,
    *,
    token: str,
    name: str,
    arguments: dict[str, object],
    idempotency_key: str | None = None,
    source_event_cursor: int | None = None,
    verification_settings: Settings | None = None,
) -> dict[str, object]:
    """The only production research-tool dispatcher; names are fixed and fail closed."""

    capability, run, manifest = authorize_tool(session, token=token, tool_name=name)
    if name not in allowed_tools(session, run):
        raise ToolCapabilityInvalid
    if name in VERIFICATION_TOOL_NAMES:
        from polycolab.verification import tools as verification_tools

        mutating = name in {"submit_verification", "cancel_verification"}
        if verification_settings is None or (
            mutating and (idempotency_key is None or source_event_cursor is None)
        ):
            raise ToolCapabilityInvalid
        try:
            if name == "submit_verification":
                submission = VersionJobSubmission.model_validate(arguments).historical_command()
                result = verification_tools.execute(
                    session,
                    token=token,
                    name=name,
                    project_id=run.project_id,
                    settings=verification_settings,
                    submission=submission,
                    retry_key=idempotency_key,
                    source_event_cursor=source_event_cursor,
                )
            else:
                reference = VerificationJobReference.model_validate(arguments)
                result = verification_tools.execute(
                    session,
                    token=token,
                    name=name,
                    project_id=run.project_id,
                    settings=verification_settings,
                    job_id=reference.job_id,
                    invocation_key=idempotency_key,
                    source_event_cursor=source_event_cursor,
                )
            return VersionJobRead.from_stored(result).model_dump(mode="json")
        except ValidationError, AuthorizationDenied, ContextInvalid, ToolCapabilityInvalid:
            session.rollback()
            raise ToolCapabilityInvalid from None
    if name in DIRECT_TOOL_NAMES:
        if idempotency_key is None or source_event_cursor is None:
            raise ToolCapabilityInvalid
        from polycolab.research.direct_contributions import mutate

        try:
            payload: (
                RecordWrite
                | ScopedRelationWrite
                | ResearchSummaryToolWrite
                | ResearchCommentToolWrite
                | ResearchProgressToolWrite
                | AgentReviewWrite
            )
            if name == "write_object_version":
                version_request = AgentObjectVersionWrite.model_validate(arguments)
                payload = agent_snapshot_command(version_request)
                destination = version_request.destination
            elif name == "create_relation":
                relation_request = AgentRelationshipWrite.model_validate(arguments).root
                payload = declaration_command(relation_request)
                destination = relation_request.destination
            elif name == "review_object_version":
                payload = AgentReviewWrite.model_validate(arguments)
            elif name == "write_summary":
                summary_request = AgentSummaryVersionWrite.model_validate(arguments)
                payload = ResearchSummaryToolWrite(
                    **summary_request.historical_command().model_dump(),
                    object_id=summary_request.object_id,
                )
            elif name == "comment_on_object_version":
                comment_request = AgentObjectVersionComment.model_validate(arguments)
                payload = ResearchCommentToolWrite(
                    object_id=comment_request.object_id,
                    project_id=comment_request.project_id,
                    revision_id=comment_request.object_version_id,
                    body_md=comment_request.body_md,
                )
            else:
                progress_request = AgentObjectVersionProgress.model_validate(arguments)
                payload = ResearchProgressToolWrite(
                    object_id=progress_request.object_id,
                    project_id=progress_request.project_id,
                    revision_id=progress_request.object_version_id,
                    status=progress_request.status,
                    detail_md=progress_request.detail_md,
                )
            if name in {"write_object_version", "create_relation"} and isinstance(
                destination, VersionLibraryDestination
            ):
                authority = run_grants.requested(session, run.id)
                if (
                    authority is None
                    or destination.statement_object_version_id
                    not in authority.public_target_revision_ids
                ):
                    raise AuthorizationDenied("Library destination not granted")
            manifest_revisions(session, manifest=manifest)
            saved = mutate(
                session,
                run=run,
                capability=capability,
                manifest=manifest,
                name=name,
                payload=payload,
                invocation=idempotency_key,
                source_cursor=source_event_cursor,
            )
            if (
                name in {"write_object_version", "comment_on_object_version", "report_progress"}
                and "revision_id" in saved
            ):
                return {
                    "object_version_id" if key == "revision_id" else key: value
                    for key, value in saved.items()
                }
            if name == "write_summary":
                return ResearchSummaryVersionRead.model_validate(saved).model_dump(mode="json")
            return saved
        except ValueError, AuthorizationDenied, ContextInvalid:
            session.rollback()
            raise ToolCapabilityInvalid from None
    actor = _actor_for_validated_tool(capability, run=run, tool_name=name)
    _validated_tool_arguments(name, arguments)
    try:
        pinned = {str(row.id): row for row in manifest_revisions(session, manifest=manifest)}
        pinned_artifacts = manifest_artifacts(session, manifest=manifest)
        authority = run_grants.requested(session, run.id)
        if authority is not None:
            output_ids = session.scalars(
                select(SqlRunRevisionOutput.revision_id)
                .where(SqlRunRevisionOutput.run_id == run.id)
                .limit(50)
            )
            for revision_id in output_ids:
                pinned[str(revision_id)] = accessible_revision(
                    session,
                    revision_id,
                    run.project_id if authority.destination == "WORKSPACE" else None,
                )
            output_artifacts = run_artifacts(session, run=run, limit=50)
            known_artifacts = {item.id for item in pinned_artifacts}
            pinned_artifacts.extend(
                item for item in output_artifacts if item.id not in known_artifacts
            )
    except (ContextInvalid, AuthorizationDenied) as exc:
        raise ToolCapabilityInvalid from exc

    read_project_id = (
        run.project_id if authority is None or authority.destination == "WORKSPACE" else None
    )

    def read_fields(revision: SqlObjectRevision) -> dict[str, object]:
        projected = version_reads(
            session,
            [revision],
            project_id=read_project_id,
            public=read_project_id is None or revision.project_id != read_project_id,
        )[0]
        # A run may know the selected snapshot without having been granted its
        # entire dependency closure. Do not reveal unpinned IDs through metadata.
        visible_links = [
            r
            for r in projected.structural_relationships
            if str(r.target_object_version_id) in pinned
        ]
        safe_author = projected.authorship.model_copy(
            update={
                "contribution_id": None,
                "author_user_id": None,
                "agent_id": None,
                "sponsor_user_id": None,
            }
        )
        fields = projected.model_copy(
            update={
                "previous_object_version_id": projected.previous_object_version_id
                if str(projected.previous_object_version_id) in pinned
                else None,
                "authorship": safe_author,
                "structural_relationships": [
                    r.model_copy(update={"ownership_scope_id": None, "authorship": safe_author})
                    for r in visible_links
                ],
            }
        ).model_dump(mode="json")
        fields["omitted_structural_relationship_count"] = len(
            projected.structural_relationships
        ) - len(visible_links)
        return fields

    if name == "get_context":
        return {
            "manifest_id": str(manifest.id),
            "object_versions": [
                {
                    **read_fields(value),
                    "object_id": str(value.object_id),
                }
                for value in pinned.values()
            ],
            "artifacts": [
                {
                    "id": str(value.id),
                    "sha256": value.sha256,
                    "byte_length": value.byte_length,
                    "media_type": value.media_type,
                }
                for value in pinned_artifacts
            ],
        }
    if name == "get_object_version":
        value = _object_version_argument(arguments)
        if value not in pinned:
            raise ToolCapabilityInvalid
        revision = pinned[value]
        return read_fields(revision)
    if name == "get_dependencies":
        value = _object_version_argument(arguments)
        if value not in pinned:
            raise ToolCapabilityInvalid
        revision_ids = [UUID(revision_id) for revision_id in pinned]
        relation_ids = list(
            session.scalars(
                select(SqlRelationAssertion)
                .where(
                    relation_read_condition(read_project_id),
                    or_(
                        SqlRelationAssertion.source_revision_id == UUID(value),
                        SqlRelationAssertion.target_revision_id == UUID(value),
                    ),
                    SqlRelationAssertion.source_revision_id.in_(revision_ids),
                    SqlRelationAssertion.target_revision_id.in_(revision_ids),
                )
                .order_by(SqlRelationAssertion.id)
                .limit(128)
            )
        )
        return {
            "relationships": [
                r.model_dump(mode="json")
                for r in relationship_reads(session, [row.id for row in relation_ids], public=True)
            ]
        }
    if name == "submit_proposal":
        require_proposal_submission(actor)
        if source_event_cursor is None or idempotency_key is None:
            raise ToolCapabilityInvalid
        try:
            proposal = submit_proposal(
                session,
                project_id=run.project_id,
                session_id=run.session_id,
                run_id=run.id,
                agent_version_id=run.agent_version_id,
                context_manifest_id=manifest.id,
                # Runtime-generated keys make a recovered lease replay the
                # same proposal rather than relying on provider output.
                idempotency_key=idempotency_key,
                summary=arguments["summary"],  # type: ignore[arg-type]
                changes=arguments["changes"],  # type: ignore[arg-type]
                trusted_source_event_cursors=[source_event_cursor],
                trusted_source_invocation_key=idempotency_key,
            )
        except ProposalInvalid, TypeError:
            raise ToolCapabilityInvalid from None
        return {"proposal_id": str(proposal.id)}
    raise ToolCapabilityInvalid
