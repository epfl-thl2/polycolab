"""Shared application enum values; persistence adapters preserve their storage encoding."""

from enum import StrEnum


class WorkspaceRole(StrEnum):
    OWNER = "OWNER"
    CONTRIBUTOR = "CONTRIBUTOR"
    READ_ONLY = "READ_ONLY"


class WorkspaceVisibility(StrEnum):
    PRIVATE = "PRIVATE"
    PUBLIC = "PUBLIC"


class ResearchScopeKind(StrEnum):
    WORKSPACE = "WORKSPACE"
    COMMONS = "COMMONS"


class ResearchEntityClass(StrEnum):
    STATEMENT = "STATEMENT"
    RECORD = "RECORD"


class ContributionActorKind(StrEnum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"


class MutationReceiptStatus(StrEnum):
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"


class OutboxEventStatus(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    DELIVERED = "DELIVERED"
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


class ResearchObjectKind(StrEnum):
    PROBLEM = "PROBLEM"
    DEFINITION = "DEFINITION"
    CLAIM = "CLAIM"
    PROOF = "PROOF"
    PROOF_SKETCH = "PROOF_SKETCH"
    ATTEMPT = "ATTEMPT"
    COUNTEREXAMPLE = "COUNTEREXAMPLE"
    NOTE = "NOTE"
    IDEA = "IDEA"
    DISCUSSION = "DISCUSSION"
    FORMALIZATION = "FORMALIZATION"
    COMPUTATION = "COMPUTATION"


class RelationType(StrEnum):
    DEPENDS_ON = "DEPENDS_ON"
    PROVES = "PROVES"
    ATTEMPTS = "ATTEMPTS"
    REFUTES = "REFUTES"
    USES = "USES"
    IMPLIES = "IMPLIES"
    EQUIVALENT_TO = "EQUIVALENT_TO"


class CorrespondenceStatus(StrEnum):
    MATCHES = "MATCHES"
    PARTIAL = "PARTIAL"
    MISMATCH = "MISMATCH"
    UNASSESSED = "UNASSESSED"


class ResearchProgressStatus(StrEnum):
    POTENTIAL = "POTENTIAL"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    STALLED = "STALLED"
    FAILED = "FAILED"


class ArtifactState(StrEnum):
    STAGING = "STAGING"
    COMMITTED = "COMMITTED"
    DELETING = "DELETING"
    DELETED = "DELETED"


class ArtifactResearchRole(StrEnum):
    SOURCE = "SOURCE"
    INPUT = "INPUT"
    EVIDENCE = "EVIDENCE"
    OUTPUT = "OUTPUT"
    FORMALIZATION = "FORMALIZATION"
    CERTIFICATE = "CERTIFICATE"


class VerificationLanguage(StrEnum):
    PYTHON = "PYTHON"
    LEAN = "LEAN"


class VerificationJobState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


class VerificationAttemptState(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    LEASE_LOST = "LEASE_LOST"


class VerificationReservationState(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ExecutionWorkloadClass(StrEnum):
    AGENT = "AGENT"
    INTERACTIVE_LEAN = "INTERACTIVE_LEAN"
    BACKGROUND_LEAN = "BACKGROUND_LEAN"
    PYTHON = "PYTHON"


class ExecutionTenantKind(StrEnum):
    USER = "USER"
    WORKSPACE = "WORKSPACE"


class VerificationInputRole(StrEnum):
    SOURCE = "SOURCE"
    INPUT = "INPUT"
    CERTIFICATE = "CERTIFICATE"


class VerificationOutputRole(StrEnum):
    OUTPUT = "OUTPUT"
    CERTIFICATE = "CERTIFICATE"
    DIAGNOSTIC = "DIAGNOSTIC"


class AttemptEvidenceRole(StrEnum):
    INPUT = "INPUT"
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    OUTPUT = "OUTPUT"


class ProvenanceKind(StrEnum):
    """Direct work or an accepted agent proposal decided by a human."""

    HUMAN_DIRECT = "HUMAN_DIRECT"
    AGENT_PROPOSAL = "AGENT_PROPOSAL"
    AGENT_DIRECT = "AGENT_DIRECT"


class ProposalChangeType(StrEnum):
    CREATE_OBJECT = "CREATE_OBJECT"
    CREATE_REVISION = "CREATE_REVISION"
    CREATE_RELATION = "CREATE_RELATION"
    CREATE_COMMENT = "CREATE_COMMENT"


class ProposalChangeStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ProposalDecisionAction(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class CanonicalEntityType(StrEnum):
    RESEARCH_OBJECT = "RESEARCH_OBJECT"
    OBJECT_REVISION = "OBJECT_REVISION"
    RELATION_ASSERTION = "RELATION_ASSERTION"
    RESEARCH_COMMENT = "RESEARCH_COMMENT"


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
    "WorkspaceRole",
    "WorkspaceVisibility",
    "ResearchScopeKind",
    "ResearchEntityClass",
    "ContributionActorKind",
    "MutationReceiptStatus",
    "OutboxEventStatus",
    "SocialProviderKind",
    "SocialAuthPurpose",
    "SocialIdentityAuditAction",
    "InvitationStatus",
    "AccountTokenPurpose",
    "MailPurpose",
    "MailOutboxStatus",
    "ResearchObjectKind",
    "RelationType",
    "CorrespondenceStatus",
    "ResearchProgressStatus",
    "ArtifactState",
    "ArtifactResearchRole",
    "VerificationLanguage",
    "VerificationJobState",
    "VerificationAttemptState",
    "VerificationReservationState",
    "ExecutionWorkloadClass",
    "ExecutionTenantKind",
    "VerificationInputRole",
    "VerificationOutputRole",
    "AttemptEvidenceRole",
    "ProvenanceKind",
    "ProposalChangeType",
    "ProposalChangeStatus",
    "ProposalDecisionAction",
    "CanonicalEntityType",
    "PlatformAgentKind",
    "ExecutionProfile",
    "AgentSessionStatus",
    "AgentMessageRole",
    "AgentRunStatus",
    "AgentRunEventKind",
    "UsageSource",
    "RuntimeBindingStatus",
    "RuntimeRunBindingStatus",
]
