"""Shared application enum values; persistence adapters preserve their storage encoding."""

from enum import StrEnum


class ProjectRole(StrEnum):
    OWNER = "OWNER"
    CONTRIBUTOR = "CONTRIBUTOR"
    READ_ONLY = "READ_ONLY"


class ProjectVisibility(StrEnum):
    PRIVATE = "PRIVATE"
    PUBLIC = "PUBLIC"


class MutationReceiptStatus(StrEnum):
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"


class SocialProviderKind(StrEnum):
    GOOGLE = "google"
    GITHUB = "github"


class SocialAuthPurpose(StrEnum):
    SIGN_IN = "SIGN_IN"
    LINK = "LINK"


class SocialIdentityAuditAction(StrEnum):
    CREATED = "CREATED"
    LINKED = "LINKED"
    UNLINKED = "UNLINKED"
    RELINKED = "RELINKED"


class InvitationStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REVOKED = "REVOKED"


class AccountTokenPurpose(StrEnum):
    EMAIL_VERIFICATION = "EMAIL_VERIFICATION"
    PASSWORD_RESET = "PASSWORD_RESET"


class MailPurpose(StrEnum):
    EMAIL_VERIFICATION = "EMAIL_VERIFICATION"
    PASSWORD_RESET = "PASSWORD_RESET"


class MailOutboxStatus(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    DISCARDED = "DISCARDED"


class ArtifactState(StrEnum):
    STAGING = "STAGING"
    COMMITTED = "COMMITTED"
    DELETING = "DELETING"
    DELETED = "DELETED"


class ExecutionWorkloadClass(StrEnum):
    AGENT = "AGENT"


class ExecutionTenantKind(StrEnum):
    USER = "USER"
    PROJECT = "PROJECT"


class PlatformAgentKind(StrEnum):
    RESEARCHER = "RESEARCHER"
    CRITIC = "CRITIC"


class ExecutionProfile(StrEnum):
    """Only trusted hosted execution is enabled in WP-09."""

    TRUSTED_HOSTED = "TRUSTED_HOSTED"


class AgentSessionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class AgentMessageRole(StrEnum):
    USER = "USER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"


class AgentRunStatus(StrEnum):
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class AgentRunEventKind(StrEnum):
    RUN_STARTED = "RUN_STARTED"
    ASSISTANT_DELTA = "ASSISTANT_DELTA"
    ASSISTANT_MESSAGE_COMPLETED = "ASSISTANT_MESSAGE_COMPLETED"
    USAGE_REPORTED = "USAGE_REPORTED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_CANCELLED = "RUN_CANCELLED"
    RUN_FAILED = "RUN_FAILED"
    RUN_TIMED_OUT = "RUN_TIMED_OUT"
    RUNNER_LOST = "RUNNER_LOST"
    TOOL_REQUESTED = "TOOL_REQUESTED"
    TOOL_RESULT = "TOOL_RESULT"


class UsageSource(StrEnum):
    PROVIDER_REPORTED = "PROVIDER_REPORTED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class RuntimeBindingStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class RuntimeRunBindingStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"
    LOST = "LOST"


__all__ = [
    "AccountTokenPurpose",
    "AgentMessageRole",
    "AgentRunEventKind",
    "AgentRunStatus",
    "AgentSessionStatus",
    "ArtifactState",
    "ExecutionProfile",
    "ExecutionTenantKind",
    "ExecutionWorkloadClass",
    "InvitationStatus",
    "MailOutboxStatus",
    "MailPurpose",
    "MutationReceiptStatus",
    "PlatformAgentKind",
    "ProjectRole",
    "ProjectVisibility",
    "RuntimeBindingStatus",
    "RuntimeRunBindingStatus",
    "SocialAuthPurpose",
    "SocialIdentityAuditAction",
    "SocialProviderKind",
    "UsageSource",
]
