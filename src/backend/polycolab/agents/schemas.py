"""HTTP schemas owned by the agents capability."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from polycolab.agents.proposal_version_schemas import (
    ObjectVersionProposalChange,
    ObjectVersionProposalPayloadRead,
)
from polycolab.app.schemas import ApiModel, RequestModel
from polycolab.entities.enums import (
    AgentMessageRole,
    AgentRunEventKind,
    AgentRunStatus,
    AgentSessionStatus,
    PlatformAgentKind,
    ProposalChangeStatus,
    ProposalDecisionAction,
)
from polycolab.research.version_schemas import ObjectVersionRead


class PlatformAgentRead(ApiModel):
    id: UUID
    agent_kind: PlatformAgentKind
    version: int
    display_name: str


class AgentSessionCreate(RequestModel):
    task_id: UUID | None = None
    project_id: UUID
    agent_kind: PlatformAgentKind
    title: str | None = Field(default=None, max_length=300)
    agent_version: Literal[1, 2] = 1
    harness: Literal["codex"] | None = None
    system_prompt: str | None = Field(default=None, min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def custom_configuration(self) -> AgentSessionCreate:
        if (self.harness is None) != (self.system_prompt is None):
            raise ValueError("custom sessions require a harness and system prompt")
        if self.system_prompt is not None and not self.system_prompt.strip():
            raise ValueError("system prompt must not be blank")
        return self


class AgentRunSummary(ApiModel):
    id: UUID
    status: AgentRunStatus
    cancel_requested_at: datetime | None


class AgentSessionRead(ApiModel):
    task_id: UUID | None = None
    id: UUID
    project_id: UUID
    agent_version_id: UUID
    agent_kind: PlatformAgentKind
    agent_version: int
    agent_display_name: str
    harness: Literal["codex"] | None
    system_prompt: str | None
    created_by_user_id: UUID
    title: str | None
    status: AgentSessionStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    latest_run: AgentRunSummary | None = None


class RunAuthorityLimits(RequestModel):
    """Shared limits; requested rights still require current-policy validation."""

    version: Literal[1] = 1
    destination: Literal["WORKSPACE", "PUBLIC"]
    allowed_operations: list[
        Literal[
            "CREATE_RECORD",
            "REVISE_RECORD",
            "CREATE_RELATION",
            "WRITE_SUMMARY",
            "COMMENT",
            "REPORT_PROGRESS",
            "REVIEW_RESEARCH",
            "RUN_VERIFICATION",
        ]
    ] = Field(default_factory=list, max_length=8)
    editable_object_ids: list[UUID] = Field(default_factory=list, max_length=32)
    max_mutations: int = Field(default=10, ge=1, le=50)
    max_content_bytes: int = Field(default=100_000, ge=1, le=500_000)
    public_task_md: str | None = Field(default=None, min_length=1, max_length=20_000)


class RunAuthorityRequest(RunAuthorityLimits):
    """Historical stored grant encoding; do not rename its fields or digest."""

    public_target_revision_ids: list[UUID] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def compatible(self) -> RunAuthorityRequest:
        for values in (
            self.public_target_revision_ids,
            self.allowed_operations,
            self.editable_object_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("duplicate authority fields")
        if self.destination == "PUBLIC":
            if not self.public_target_revision_ids or not (self.public_task_md or "").strip():
                raise ValueError("public runs require explicit targets and a separate public task")
            if "RUN_VERIFICATION" in self.allowed_operations:
                raise ValueError("verification jobs require a private workspace destination")
        elif self.public_target_revision_ids or self.public_task_md is not None:
            raise ValueError("workspace grants cannot include a public task or destination")
        return self


class RunObjectVersionAuthorityRequest(RunAuthorityLimits):
    public_target_object_version_ids: list[UUID] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def compatible(self) -> RunObjectVersionAuthorityRequest:
        self.historical_command()
        return self

    def historical_command(self) -> RunAuthorityRequest:
        return RunAuthorityRequest(
            **self.model_dump(exclude={"public_target_object_version_ids"}),
            public_target_revision_ids=self.public_target_object_version_ids,
        )


class AgentMessageCreate(RequestModel):
    client_request_id: UUID
    content_md: str = Field(min_length=1, max_length=200_000)
    gateway_profile_id: UUID
    context_object_version_ids: list[UUID] = Field(default_factory=list, max_length=64)
    context_artifact_ids: list[UUID] = Field(default_factory=list, max_length=32)
    requested_authority: RunObjectVersionAuthorityRequest | None = None

    @model_validator(mode="after")
    def distinct_context(self) -> AgentMessageCreate:
        if len(set(self.context_object_version_ids)) != len(self.context_object_version_ids):
            raise ValueError("duplicate context object versions")
        if len(set(self.context_artifact_ids)) != len(self.context_artifact_ids):
            raise ValueError("duplicate context artifacts")
        if (
            self.context_artifact_ids
            and self.requested_authority is not None
            and self.requested_authority.destination == "PUBLIC"
        ):
            raise ValueError("public runs cannot receive private artifact context")
        return self


class AgentMessageRead(ApiModel):
    id: UUID
    session_id: UUID
    sequence: int
    role: AgentMessageRole
    author_user_id: UUID | None
    content_md: str
    created_at: datetime


class AgentRunRead(ApiModel):
    id: UUID
    session_id: UUID
    project_id: UUID
    request_message_id: UUID | None
    parent_run_id: UUID | None
    queue_sequence: int
    status: AgentRunStatus
    attempt: int
    cancel_requested_at: datetime | None
    deadline_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    failure_code: str | None
    created_at: datetime
    updated_at: datetime


class AgentTurnQueued(BaseModel):
    message: AgentMessageRead
    run: AgentRunRead


class AgentRunResume(RequestModel):
    client_request_id: UUID
    gateway_profile_id: UUID


class AgentRunEventRead(ApiModel):
    run_id: UUID
    cursor: int
    kind: AgentRunEventKind
    payload: dict[str, object]
    occurred_at: datetime


class ProposalRead(ApiModel):
    id: UUID
    project_id: UUID
    agent_version_id: UUID
    context_manifest_id: UUID
    summary: str
    created_at: datetime


class ProposalChangeRead(ApiModel):
    id: UUID
    ordinal: int
    change_type: Literal[
        "CREATE_OBJECT", "CREATE_OBJECT_VERSION", "CREATE_RELATIONSHIP", "CREATE_COMMENT"
    ]
    payload: ObjectVersionProposalPayloadRead
    status: ProposalChangeStatus
    decided_by_user_id: UUID | None
    decided_at: datetime | None
    applied_entity_id: UUID | None
    rejection_reason: str | None


class ProposalDetailRead(ProposalRead):
    changes: list[ProposalChangeRead]


class ProposalChangeAccept(RequestModel):
    payload: ObjectVersionProposalChange | None = None


class ProposalChangeReject(RequestModel):
    reason: str | None = Field(default=None, max_length=20_000)


class ProposalBatchDecision(RequestModel):
    change_id: UUID
    action: ProposalDecisionAction
    payload: ObjectVersionProposalChange | None = None
    reason: str | None = Field(default=None, max_length=20_000)


class ProposalDecisionBatchRequest(RequestModel):
    decisions: list[ProposalBatchDecision] = Field(min_length=1, max_length=100)


ContributionEntityType = Literal[
    "RESEARCH_OBJECT", "OBJECT_VERSION", "OBJECT_VERSION_RELATIONSHIP", "RESEARCH_COMMENT"
]


class AgentContributionRead(ApiModel):
    canonical_entity_id: UUID
    canonical_entity_type: ContributionEntityType
    deciding_user_id: UUID
    created_at: datetime


class ExternalCredentialCreate(RequestModel):
    allow_reviews: bool = False
    agent_id: UUID
    allow_library_contributions: bool = False
    name: str = Field(min_length=1, max_length=200)


class ExternalCredentialRead(ApiModel):
    allow_reviews: bool = False
    secret_reveal_available: bool = False
    agent_id: UUID | None
    allow_library_contributions: bool
    id: UUID
    project_id: UUID | None
    scope_kind: Literal["ACCOUNT", "WORKSPACE"]
    sponsor_user_id: UUID
    name: str
    fixed_rights: list[str]
    expires_at: datetime
    revoked_at: datetime | None
    request_count: int
    mutation_count: int
    max_requests: int
    max_mutations: int
    created_at: datetime


class ExternalCredentialIssued(ExternalCredentialRead):
    # List projections never contain this field.
    secret: str


class ExternalRunCreate(RequestModel):
    workspace_id: UUID
    client_request_id: UUID
    title: str | None = Field(default=None, max_length=300)
    input_revision_ids: list[UUID] = Field(default_factory=list, max_length=100)


class ExternalRunClose(RequestModel):
    status: Literal["COMPLETED", "FAILED"]
    failure_code: str | None = Field(default=None, min_length=1, max_length=64)


class ExternalRunRead(ApiModel):
    id: UUID
    credential_id: UUID
    project_id: UUID
    sponsor_user_id: UUID
    client_request_id: UUID
    title: str | None
    input_object_version_ids: list[UUID] = Field(validation_alias="input_revision_ids")
    status: Literal["OPEN", "COMPLETED", "FAILED", "REVOKED"]
    failure_code: str | None
    created_at: datetime
    closed_at: datetime | None


class ExternalRunOutputRead(ApiModel):
    entity_type: str
    entity_id: UUID


class ExternalRunDetail(ExternalRunRead):
    outputs: list[ExternalRunOutputRead]


class ExternalMutationRead(ApiModel):
    replayed: bool
    outputs: list[ExternalRunOutputRead]


class PublicExternalRunRead(BaseModel):
    id: UUID
    agent_name: str
    sponsor_display_name: str | None
    title: str | None
    input_revision_ids: list[UUID]
    outputs: list[ExternalRunOutputRead]
    status: Literal["OPEN", "COMPLETED", "FAILED", "REVOKED"]
    failure_code: str | None
    created_at: datetime
    closed_at: datetime | None


class ExternalAgentDiscovery(ApiModel):
    credential_id: UUID
    destination_project_id: UUID | None
    fixed_rights: list[str]
    expires_at: datetime
    max_requests: int
    max_mutations: int


class ContextManifestRead(ApiModel):
    id: UUID
    run_id: UUID
    project_id: UUID
    object_version_ids: list[UUID]
    artifact_ids: list[UUID]
    digest: str
    created_at: datetime
    object_versions: list[ObjectVersionRead]


__all__ = [
    "PlatformAgentRead",
    "AgentSessionCreate",
    "AgentSessionRead",
    "RunAuthorityRequest",
    "RunObjectVersionAuthorityRequest",
    "AgentMessageCreate",
    "AgentMessageRead",
    "AgentRunRead",
    "AgentRunSummary",
    "AgentTurnQueued",
    "AgentRunResume",
    "AgentRunEventRead",
    "ProposalRead",
    "ProposalChangeRead",
    "ProposalDetailRead",
    "ProposalChangeAccept",
    "ProposalChangeReject",
    "ProposalBatchDecision",
    "ProposalDecisionBatchRequest",
    "AgentContributionRead",
    "ExternalCredentialCreate",
    "ExternalCredentialRead",
    "ExternalCredentialIssued",
    "ExternalRunCreate",
    "ExternalRunClose",
    "ExternalRunRead",
    "ExternalRunOutputRead",
    "ExternalRunDetail",
    "ExternalMutationRead",
    "PublicExternalRunRead",
    "ExternalAgentDiscovery",
    "ContextManifestRead",
]
