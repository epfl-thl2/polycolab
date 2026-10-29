"""Canonical SQLAlchemy entity registry.

Importing this package registers every mapped class for SQLAlchemy and Alembic.
"""

from polycolab.db.models.accounts import SqlAccountEmail as SqlAccountEmail
from polycolab.db.models.accounts import (
    SqlAccountRecoveryRateWindow as SqlAccountRecoveryRateWindow,
)
from polycolab.db.models.accounts import SqlAccountRecoveryToken as SqlAccountRecoveryToken
from polycolab.db.models.accounts import SqlAuthSession as SqlAuthSession
from polycolab.db.models.accounts import SqlLocalAccount as SqlLocalAccount
from polycolab.db.models.accounts import SqlMailOutbox as SqlMailOutbox
from polycolab.db.models.accounts import SqlRegistrationInvitation as SqlRegistrationInvitation
from polycolab.db.models.accounts import SqlSocialAccountIdentity as SqlSocialAccountIdentity
from polycolab.db.models.accounts import SqlSocialAuthTransaction as SqlSocialAuthTransaction
from polycolab.db.models.accounts import SqlSocialIdentityAudit as SqlSocialIdentityAudit
from polycolab.db.models.accounts import SqlUser as SqlUser
from polycolab.db.models.agent_access import (
    SqlExternalAgentCredential as SqlExternalAgentCredential,
)
from polycolab.db.models.agent_access import SqlExternalAgentIdentity as SqlExternalAgentIdentity
from polycolab.db.models.agents import SqlAgentMessage as SqlAgentMessage
from polycolab.db.models.agents import SqlAgentRun as SqlAgentRun
from polycolab.db.models.agents import SqlAgentRunEvent as SqlAgentRunEvent
from polycolab.db.models.agents import SqlAgentRunUsage as SqlAgentRunUsage
from polycolab.db.models.agents import SqlAgentSession as SqlAgentSession
from polycolab.db.models.agents import SqlContextManifest as SqlContextManifest
from polycolab.db.models.agents import SqlContextManifestArtifact as SqlContextManifestArtifact
from polycolab.db.models.agents import SqlExecutionRateWindow as SqlExecutionRateWindow
from polycolab.db.models.agents import SqlHostedCompletion as SqlHostedCompletion
from polycolab.db.models.agents import SqlHostedExecutor as SqlHostedExecutor
from polycolab.db.models.agents import SqlHostedRunArtifact as SqlHostedRunArtifact
from polycolab.db.models.agents import SqlHostedSlot as SqlHostedSlot
from polycolab.db.models.agents import (
    SqlOperationalMetricAggregate as SqlOperationalMetricAggregate,
)
from polycolab.db.models.agents import SqlOperatorDiagnosticAccess as SqlOperatorDiagnosticAccess
from polycolab.db.models.agents import SqlPlatformAgentVersion as SqlPlatformAgentVersion
from polycolab.db.models.agents import SqlRuntimeRunBinding as SqlRuntimeRunBinding
from polycolab.db.models.agents import SqlRuntimeSessionBinding as SqlRuntimeSessionBinding
from polycolab.db.models.agents import SqlRunToolCapability as SqlRunToolCapability
from polycolab.db.models.artifacts import SqlArtifact as SqlArtifact
from polycolab.db.models.execution import SqlExecutionClassState as SqlExecutionClassState
from polycolab.db.models.execution import SqlExecutionFairnessState as SqlExecutionFairnessState
from polycolab.db.models.execution import SqlExecutionSlotLease as SqlExecutionSlotLease
from polycolab.db.models.execution import SqlExecutionWorkItem as SqlExecutionWorkItem
from polycolab.db.models.model_gateway import (
    SqlGatewayCredentialRewrapAudit as SqlGatewayCredentialRewrapAudit,
)
from polycolab.db.models.model_gateway import SqlGatewayProfile as SqlGatewayProfile
from polycolab.db.models.model_gateway import SqlGatewayRunGrant as SqlGatewayRunGrant
from polycolab.db.models.model_gateway import SqlHostedModelRequest as SqlHostedModelRequest
from polycolab.db.models.operations import SqlOperatorAccountRecovery as SqlOperatorAccountRecovery
from polycolab.db.models.operations import (
    SqlOperatorRestoreInvalidation as SqlOperatorRestoreInvalidation,
)
from polycolab.db.models.platform import SqlMutationReceipt as SqlMutationReceipt
from polycolab.db.models.projects import SqlInvitation as SqlInvitation
from polycolab.db.models.projects import SqlMembership as SqlMembership
from polycolab.db.models.projects import SqlProject as SqlProject
from polycolab.entities.enums import AccountTokenPurpose as AccountTokenPurpose
from polycolab.entities.enums import AgentMessageRole as AgentMessageRole
from polycolab.entities.enums import AgentRunEventKind as AgentRunEventKind
from polycolab.entities.enums import AgentRunStatus as AgentRunStatus
from polycolab.entities.enums import AgentSessionStatus as AgentSessionStatus
from polycolab.entities.enums import ArtifactState as ArtifactState
from polycolab.entities.enums import ExecutionProfile as ExecutionProfile
from polycolab.entities.enums import ExecutionTenantKind as ExecutionTenantKind
from polycolab.entities.enums import ExecutionWorkloadClass as ExecutionWorkloadClass
from polycolab.entities.enums import InvitationStatus as InvitationStatus
from polycolab.entities.enums import MailOutboxStatus as MailOutboxStatus
from polycolab.entities.enums import MailPurpose as MailPurpose
from polycolab.entities.enums import MutationReceiptStatus as MutationReceiptStatus
from polycolab.entities.enums import PlatformAgentKind as PlatformAgentKind
from polycolab.entities.enums import ProjectRole as ProjectRole
from polycolab.entities.enums import ProjectVisibility as ProjectVisibility
from polycolab.entities.enums import RuntimeBindingStatus as RuntimeBindingStatus
from polycolab.entities.enums import RuntimeRunBindingStatus as RuntimeRunBindingStatus
from polycolab.entities.enums import SocialAuthPurpose as SocialAuthPurpose
from polycolab.entities.enums import SocialIdentityAuditAction as SocialIdentityAuditAction
from polycolab.entities.enums import SocialProviderKind as SocialProviderKind
from polycolab.entities.enums import UsageSource as UsageSource

__all__ = [
    "SqlAgentLibraryEntry",
    "SqlAgentLibraryDraft",
    "SqlAgentLibraryVersion",
    "SqlAgentLibraryModeration",
    "ProjectRole",
    "ProjectVisibility",
    "MutationReceiptStatus",
    "SocialProviderKind",
    "SocialAuthPurpose",
    "SocialIdentityAuditAction",
    "InvitationStatus",
    "AccountTokenPurpose",
    "MailPurpose",
    "MailOutboxStatus",
    "ArtifactState",
    "ExecutionWorkloadClass",
    "ExecutionTenantKind",
    "PlatformAgentKind",
    "ExecutionProfile",
    "AgentSessionStatus",
    "AgentMessageRole",
    "AgentRunStatus",
    "AgentRunEventKind",
    "UsageSource",
    "RuntimeBindingStatus",
    "RuntimeRunBindingStatus",
    "SqlUser",
    "SqlLocalAccount",
    "SqlAuthSession",
    "SqlRegistrationInvitation",
    "SqlAccountEmail",
    "SqlAccountRecoveryToken",
    "SqlMailOutbox",
    "SqlAccountRecoveryRateWindow",
    "SqlSocialAccountIdentity",
    "SqlSocialAuthTransaction",
    "SqlSocialIdentityAudit",
    "SqlGatewayProfile",
    "SqlGatewayCredentialRewrapAudit",
    "SqlGatewayRunGrant",
    "SqlProject",
    "SqlMembership",
    "SqlInvitation",
    "SqlPlatformAgentVersion",
    "SqlAgentSession",
    "SqlAgentMessage",
    "SqlAgentRun",
    "SqlAgentRunEvent",
    "SqlAgentRunUsage",
    "SqlExecutionRateWindow",
    "SqlOperationalMetricAggregate",
    "SqlOperatorDiagnosticAccess",
    "SqlRuntimeSessionBinding",
    "SqlRuntimeRunBinding",
    "SqlContextManifest",
    "SqlContextManifestArtifact",
    "SqlRunToolCapability",
    "SqlExternalAgentCredential",
    "SqlExternalAgentIdentity",
    "SqlArtifact",
    "SqlExecutionWorkItem",
    "SqlExecutionClassState",
    "SqlExecutionFairnessState",
    "SqlExecutionSlotLease",
    "SqlOperatorAccountRecovery",
    "SqlOperatorRestoreInvalidation",
    "SqlMutationReceipt",
    "SqlHostedModelRequest",
    "SqlHostedRunArtifact",
    "SqlHostedExecutor",
    "SqlHostedCompletion",
    "SqlHostedSlot",
    "SqlRepositoryMutation",
    "SqlRepositoryRun",
    "SqlRepositorySession",
    "SqlProjectRepository",
    "SqlProjectTask",
    "SqlChatConversation",
    "SqlChatTurn",
    "SqlDocumentBuild",
    "SqlDocumentBuildQueue",
]

from polycolab.db.models.agent_library import (
    SqlAgentLibraryDraft as SqlAgentLibraryDraft,
)
from polycolab.db.models.agent_library import (
    SqlAgentLibraryEntry as SqlAgentLibraryEntry,
)
from polycolab.db.models.agent_library import (
    SqlAgentLibraryModeration as SqlAgentLibraryModeration,
)
from polycolab.db.models.agent_library import (
    SqlAgentLibraryVersion as SqlAgentLibraryVersion,
)
from polycolab.db.models.chat import SqlChatConversation as SqlChatConversation
from polycolab.db.models.chat import SqlChatTurn as SqlChatTurn
from polycolab.db.models.document_builds import SqlDocumentBuild as SqlDocumentBuild
from polycolab.db.models.document_builds import SqlDocumentBuildQueue as SqlDocumentBuildQueue
from polycolab.db.models.linear import (
    SqlLinearBatch as SqlLinearBatch,
)
from polycolab.db.models.linear import (
    SqlLinearCheckpoint as SqlLinearCheckpoint,
)
from polycolab.db.models.linear import SqlLinearConversion as SqlLinearConversion
from polycolab.db.models.linear import (
    SqlLinearFile as SqlLinearFile,
)
from polycolab.db.models.linear import (
    SqlLinearOperation as SqlLinearOperation,
)
from polycolab.db.models.linear import (
    SqlLinearRun as SqlLinearRun,
)
from polycolab.db.models.linear import (
    SqlLinearWorkspace as SqlLinearWorkspace,
)
from polycolab.db.models.project_tasks import SqlProjectTask as SqlProjectTask
from polycolab.db.models.repositories import (
    SqlProjectRepository as SqlProjectRepository,
)
from polycolab.db.models.repositories import (
    SqlRepositoryMutation as SqlRepositoryMutation,
)
from polycolab.db.models.repositories import (
    SqlRepositoryRun as SqlRepositoryRun,
)
from polycolab.db.models.repositories import (
    SqlRepositorySession as SqlRepositorySession,
)
