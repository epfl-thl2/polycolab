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
    SqlAgentApiKey as SqlAgentApiKey,
)
from polycolab.db.models.agents import SqlAgentRun as SqlAgentRun
from polycolab.db.models.agents import SqlAgentRunEvent as SqlAgentRunEvent
from polycolab.db.models.agents import SqlAgentRunUsage as SqlAgentRunUsage
from polycolab.db.models.agents import SqlContextManifest as SqlContextManifest
from polycolab.db.models.agents import SqlContextManifestArtifact as SqlContextManifestArtifact
from polycolab.db.models.agents import SqlConversation as SqlConversation
from polycolab.db.models.agents import SqlConversationConfiguration as SqlConversationConfiguration
from polycolab.db.models.agents import SqlConversationItem as SqlConversationItem
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
from polycolab.db.models.execution import SqlExecutionJob as SqlExecutionJob
from polycolab.db.models.execution import SqlExecutionSlotLease as SqlExecutionSlotLease
from polycolab.db.models.model_gateway import (
    SqlGatewayCredentialRewrapAudit as SqlGatewayCredentialRewrapAudit,
)
from polycolab.db.models.model_gateway import SqlGatewayRunGrant as SqlGatewayRunGrant
from polycolab.db.models.model_gateway import SqlHostedModelRequest as SqlHostedModelRequest
from polycolab.db.models.model_gateway import SqlProviderConnection as SqlProviderConnection
from polycolab.db.models.operations import SqlOperatorAccountRecovery as SqlOperatorAccountRecovery
from polycolab.db.models.operations import (
    SqlOperatorRestoreInvalidation as SqlOperatorRestoreInvalidation,
)
from polycolab.db.models.platform import SqlIdempotencyRecord as SqlIdempotencyRecord
from polycolab.db.models.projects import SqlInvitation as SqlInvitation
from polycolab.db.models.projects import SqlMembership as SqlMembership
from polycolab.db.models.projects import SqlProject as SqlProject
from polycolab.entities.enums import AccountTokenPurpose as AccountTokenPurpose
from polycolab.entities.enums import AgentMessageRole as AgentMessageRole
from polycolab.entities.enums import AgentRunEventKind as AgentRunEventKind
from polycolab.entities.enums import AgentRunStatus as AgentRunStatus
from polycolab.entities.enums import ArtifactState as ArtifactState
from polycolab.entities.enums import ExecutionProfile as ExecutionProfile
from polycolab.entities.enums import ExecutionWorkloadClass as ExecutionWorkloadClass
from polycolab.entities.enums import IdempotencyRecordStatus as IdempotencyRecordStatus
from polycolab.entities.enums import InvitationStatus as InvitationStatus
from polycolab.entities.enums import MailOutboxStatus as MailOutboxStatus
from polycolab.entities.enums import MailPurpose as MailPurpose
from polycolab.entities.enums import PlatformAgentKind as PlatformAgentKind
from polycolab.entities.enums import ProjectRole as ProjectRole
from polycolab.entities.enums import ProjectVisibility as ProjectVisibility
from polycolab.entities.enums import RuntimeBindingStatus as RuntimeBindingStatus
from polycolab.entities.enums import RuntimeRunBindingStatus as RuntimeRunBindingStatus
from polycolab.entities.enums import SchedulingScopeKind as SchedulingScopeKind
from polycolab.entities.enums import SocialAuthPurpose as SocialAuthPurpose
from polycolab.entities.enums import SocialIdentityAuditAction as SocialIdentityAuditAction
from polycolab.entities.enums import SocialProviderKind as SocialProviderKind
from polycolab.entities.enums import StoredConversationStatus as StoredConversationStatus
from polycolab.entities.enums import UsageSource as UsageSource

__all__ = [
    "SqlLibraryItem",
    "SqlLibraryDraft",
    "SqlLibraryVersion",
    "SqlLibraryModeration",
    "ProjectRole",
    "ProjectVisibility",
    "IdempotencyRecordStatus",
    "SocialProviderKind",
    "SocialAuthPurpose",
    "SocialIdentityAuditAction",
    "InvitationStatus",
    "AccountTokenPurpose",
    "MailPurpose",
    "MailOutboxStatus",
    "ArtifactState",
    "ExecutionWorkloadClass",
    "SchedulingScopeKind",
    "PlatformAgentKind",
    "ExecutionProfile",
    "StoredConversationStatus",
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
    "SqlProviderConnection",
    "SqlGatewayCredentialRewrapAudit",
    "SqlGatewayRunGrant",
    "SqlProject",
    "SqlMembership",
    "SqlInvitation",
    "SqlPlatformAgentVersion",
    "SqlConversation",
    "SqlConversationItem",
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
    "SqlAgentApiKey",
    "SqlArtifact",
    "SqlExecutionJob",
    "SqlExecutionClassState",
    "SqlExecutionFairnessState",
    "SqlExecutionSlotLease",
    "SqlOperatorAccountRecovery",
    "SqlOperatorRestoreInvalidation",
    "SqlIdempotencyRecord",
    "SqlHostedModelRequest",
    "SqlHostedRunArtifact",
    "SqlHostedExecutor",
    "SqlHostedCompletion",
    "SqlHostedSlot",
    "SqlRepositoryIdempotencyRecord",
    "SqlRepositoryRun",
    "SqlRepositoryConversation",
    "SqlProjectRepository",
    "SqlWorktree",
    "SqlLegacyConversationExecution",
    "SqlConversationConfiguration",
    "SqlDocumentBuild",
    "SqlDocumentBuildQueue",
]

from polycolab.db.models.collaborative import (
    SqlChangeSet as SqlChangeSet,
)
from polycolab.db.models.collaborative import (
    SqlCollaborativeCheckpoint as SqlCollaborativeCheckpoint,
)
from polycolab.db.models.collaborative import (
    SqlCollaborativeConversion as SqlCollaborativeConversion,
)
from polycolab.db.models.collaborative import (
    SqlCollaborativeFile as SqlCollaborativeFile,
)
from polycolab.db.models.collaborative import (
    SqlCollaborativeOperation as SqlCollaborativeOperation,
)
from polycolab.db.models.collaborative import (
    SqlCollaborativeRun as SqlCollaborativeRun,
)
from polycolab.db.models.collaborative import (
    SqlCollaborativeWorkspace as SqlCollaborativeWorkspace,
)
from polycolab.db.models.conversations import (
    SqlLegacyConversationExecution as SqlLegacyConversationExecution,
)
from polycolab.db.models.document_builds import SqlDocumentBuild as SqlDocumentBuild
from polycolab.db.models.document_builds import SqlDocumentBuildQueue as SqlDocumentBuildQueue
from polycolab.db.models.library import (
    SqlLibraryDraft as SqlLibraryDraft,
)
from polycolab.db.models.library import (
    SqlLibraryItem as SqlLibraryItem,
)
from polycolab.db.models.library import (
    SqlLibraryModeration as SqlLibraryModeration,
)
from polycolab.db.models.library import (
    SqlLibraryVersion as SqlLibraryVersion,
)
from polycolab.db.models.repositories import (
    SqlProjectRepository as SqlProjectRepository,
)
from polycolab.db.models.repositories import (
    SqlRepositoryConversation as SqlRepositoryConversation,
)
from polycolab.db.models.repositories import (
    SqlRepositoryIdempotencyRecord as SqlRepositoryIdempotencyRecord,
)
from polycolab.db.models.repositories import (
    SqlRepositoryRun as SqlRepositoryRun,
)
from polycolab.db.models.worktrees import SqlWorktree as SqlWorktree
