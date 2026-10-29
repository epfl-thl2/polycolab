"""Narrow WP-10 tool-capability issue and verification boundary."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.access.authorization import (
    ROLE_ACTIONS,
    AuthorizationDenied,
    ProjectAction,
    lock_project_authorization,
    project_policy,
)
from polycolab.agents.context import (
    ContextInvalid,
    manifest_artifacts,
)
from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentSession,
    SqlContextManifest,
    SqlRunToolCapability,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import AgentRunStatus, AgentSessionStatus
from polycolab.entities.time import utc_now
from polycolab.platform.config import Settings

TOOL_NAMES = frozenset({"get_context"})
ALL_TOOL_NAMES = TOOL_NAMES | {"project_files"}


def allowed_tools(session: Session, run: SqlAgentRun) -> frozenset[str]:
    names = set(TOOL_NAMES)
    from polycolab.db.models import SqlProject

    project = session.get(SqlProject, run.project_id)
    if project is not None and project.workspace_mode == "default":
        names.add("project_files")
    return frozenset(names)


def definitions(session: Session, run: SqlAgentRun) -> list[dict[str, object]]:
    values = list(PLATFORM_TOOL_DEFINITIONS)
    names = allowed_tools(session, run)
    if "project_files" in names:
        from polycolab.projects.default_files import DefaultAgentFileCommand

        values.append(
            {
                "type": "function",
                "function": {
                    "name": "project_files",
                    "description": (
                        "Access current files in this project's server directory. "
                        "List or read before editing. Writes, renames, and deletes apply "
                        "immediately without version history. Use the read digest as "
                        "expected_digest; omit it only to create a file. Use content for "
                        "UTF-8 text or content_base64 for binary data. These files are "
                        "accessed through this tool, not mounted in your execution directory. "
                        "Read returns byte ranges; list returns at most 100 files. Continue "
                        "with next_offset and the same expected_digest for further read ranges."
                    ),
                    "parameters": DefaultAgentFileCommand.model_json_schema(),
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
            "description": "Read the run's project and pinned artifact context.",
            "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
        },
    },
)


class ToolCapabilityInvalid(Exception):
    pass


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
        or not project_policy.can(
            SqlAlchemyTransaction(session),
            run.project_id,
            run.requested_by_user_id,
            ProjectAction.RUN_AGENTS,
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
    session: Session, *, project_id: UUID, user_id: UUID, action: ProjectAction
) -> bool:
    project, membership = lock_project_authorization(
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
    lock_project_authorization(
        SqlAlchemyTransaction(session), project_id=candidate.project_id, user_id=candidate.user_id
    )
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
        or tool_name not in ALL_TOOL_NAMES
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
            action=ProjectAction.RUN_AGENTS,
        )
        or not _locked_current_scope(
            session,
            project_id=run.project_id,
            user_id=parent.created_by_user_id,
            action=ProjectAction.VIEW,
        )
    ):
        raise ToolCapabilityInvalid
    return capability, run, manifest


def execute_tool(
    session: Session,
    *,
    token: str,
    name: str,
    arguments: dict[str, object],
    idempotency_key: str | None = None,
    source_event_cursor: int | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    """Dispatch only the fixed workspace tools under current run authority."""

    capability, run, manifest = authorize_tool(session, token=token, tool_name=name)
    if name not in allowed_tools(session, run):
        raise ToolCapabilityInvalid
    if name == "project_files":
        from polycolab.projects.default_files import (
            DefaultAgentFileCommand,
            DefaultFiles,
            agent_result,
        )

        if (
            settings is None
            or settings.project_repository_directory is None
            or idempotency_key is None
            or source_event_cursor is None
        ):
            raise ToolCapabilityInvalid
        try:
            command = DefaultAgentFileCommand.model_validate(arguments)
        except ValidationError as exc:
            raise ToolCapabilityInvalid from exc
        files = DefaultFiles(
            SqlAlchemyTransaction(session),
            settings.project_repository_directory,
            run.project_id,
            run.requested_by_user_id,
            settings.project_repository_max_bytes,
        )
        file_result = agent_result(files, command)
        session.commit()
        return file_result
    if name != "get_context" or arguments:
        raise ToolCapabilityInvalid
    try:
        pinned_artifacts = manifest_artifacts(session, manifest=manifest)
    except (ContextInvalid, AuthorizationDenied) as exc:
        raise ToolCapabilityInvalid from exc
    return {
        "manifest_id": str(manifest.id),
        "project_id": str(run.project_id),
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
