"""Trusted actor identity and delegated authority values."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class ActorKind(StrEnum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"


class ActorOperation(StrEnum):
    CATALOGUE_ADMISSION = "CATALOGUE_ADMISSION"
    CATALOGUE_PROMOTION = "CATALOGUE_PROMOTION"
    CATALOGUE_EDIT = "CATALOGUE_EDIT"
    REVIEW_RESEARCH = "REVIEW_RESEARCH"
    CONTRIBUTION_CREATE = "CONTRIBUTION_CREATE"
    CONTRIBUTION_EDIT = "CONTRIBUTION_EDIT"
    PUBLIC_PARTICIPATION = "PUBLIC_PARTICIPATION"
    PROJECT_WRITE = "PROJECT_WRITE"
    PUBLICATION = "PUBLICATION"
    MANAGE_MEMBERS = "MANAGE_MEMBERS"
    MANAGE_CREDENTIALS = "MANAGE_CREDENTIALS"
    MODERATION = "MODERATION"
    PROPOSAL_SUBMISSION = "PROPOSAL_SUBMISSION"
    PROPOSAL_REVIEW = "PROPOSAL_REVIEW"


@dataclass(frozen=True, slots=True)
class Actor:
    """Server-constructed authority; no field is accepted from a request body."""

    kind: ActorKind
    human_user_id: UUID | None = None
    sponsor_user_id: UUID | None = None
    agent_version_id: UUID | None = None
    run_id: UUID | None = None
    capability_id: UUID | None = None
    session_id: UUID | None = None
    context_manifest_id: UUID | None = None
    project_id: UUID | None = None
    ownership_scope_id: UUID | None = None
    external_credential_id: UUID | None = None
    external_run_id: UUID | None = None
    external_agent_id: UUID | None = None
    operation_scope: frozenset[ActorOperation] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.kind is ActorKind.HUMAN:
            if self.human_user_id is None or any(
                value is not None
                for value in (
                    self.sponsor_user_id,
                    self.agent_version_id,
                    self.run_id,
                    self.capability_id,
                    self.session_id,
                    self.context_manifest_id,
                    self.project_id,
                    self.ownership_scope_id,
                    self.external_credential_id,
                    self.external_run_id,
                    self.external_agent_id,
                )
            ):
                raise ValueError("human actors cannot carry agent or delegated scope")
            if self.operation_scope:
                raise ValueError("human actors do not carry delegated operations")
            return
        if self.kind is not ActorKind.AGENT:
            raise ValueError("unsupported actor kind")
        hosted = all(
            value is not None
            for value in (
                self.agent_version_id,
                self.run_id,
                self.capability_id,
                self.session_id,
                self.context_manifest_id,
            )
        )
        external = self.external_credential_id is not None and (
            self.external_run_id is not None or self.external_agent_id is not None
        )
        if (
            self.human_user_id is not None
            or self.sponsor_user_id is None
            or (self.project_id is None and self.external_agent_id is None)
            or hosted == external
        ):
            raise ValueError("agent actors require validated delegated references")
