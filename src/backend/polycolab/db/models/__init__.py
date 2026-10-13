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
from polycolab.db.models.agents import SqlAgentMessage as SqlAgentMessage
from polycolab.db.models.agents import SqlAgentRun as SqlAgentRun
from polycolab.db.models.agents import SqlAgentRunEvent as SqlAgentRunEvent
from polycolab.db.models.agents import SqlAgentRunUsage as SqlAgentRunUsage
from polycolab.db.models.agents import SqlAgentSession as SqlAgentSession
from polycolab.db.models.agents import SqlContextManifest as SqlContextManifest
from polycolab.db.models.agents import SqlContextManifestArtifact as SqlContextManifestArtifact
from polycolab.db.models.agents import SqlExecutionRateWindow as SqlExecutionRateWindow
from polycolab.db.models.agents import SqlExternalResearchRun as SqlExternalResearchRun
from polycolab.db.models.agents import SqlExternalRunInvocation as SqlExternalRunInvocation
from polycolab.db.models.agents import SqlHostedCompletion as SqlHostedCompletion
from polycolab.db.models.agents import SqlHostedExecutor as SqlHostedExecutor
from polycolab.db.models.agents import SqlHostedRunArtifact as SqlHostedRunArtifact
from polycolab.db.models.agents import SqlHostedSlot as SqlHostedSlot
from polycolab.db.models.agents import (
    SqlOperationalMetricAggregate as SqlOperationalMetricAggregate,
)
from polycolab.db.models.agents import SqlOperatorDiagnosticAccess as SqlOperatorDiagnosticAccess
from polycolab.db.models.agents import SqlPlatformAgentVersion as SqlPlatformAgentVersion
from polycolab.db.models.agents import SqlProposal as SqlProposal
from polycolab.db.models.agents import SqlProposalChange as SqlProposalChange
from polycolab.db.models.agents import SqlProposalChangeDecision as SqlProposalChangeDecision
from polycolab.db.models.agents import SqlProposalDecisionBatch as SqlProposalDecisionBatch
from polycolab.db.models.agents import SqlRunArtifactOutput as SqlRunArtifactOutput
from polycolab.db.models.agents import SqlRunRevisionOutput as SqlRunRevisionOutput
from polycolab.db.models.agents import SqlRuntimeRunBinding as SqlRuntimeRunBinding
from polycolab.db.models.agents import SqlRuntimeSessionBinding as SqlRuntimeSessionBinding
from polycolab.db.models.agents import SqlRunToolCapability as SqlRunToolCapability
from polycolab.db.models.agents import SqlRunWriteGrant as SqlRunWriteGrant
from polycolab.db.models.artifacts import SqlArtifact as SqlArtifact
from polycolab.db.models.artifacts import SqlArtifactResearchLink as SqlArtifactResearchLink
from polycolab.db.models.artifacts import (
    SqlPublicationArtifactMember as SqlPublicationArtifactMember,
)
from polycolab.db.models.catalogue import SqlCatalogueAudit as SqlCatalogueAudit
from polycolab.db.models.catalogue import SqlCatalogueEntry as SqlCatalogueEntry
from polycolab.db.models.catalogue import SqlCatalogueFollow as SqlCatalogueFollow
from polycolab.db.models.catalogue import SqlCatalogueInterest as SqlCatalogueInterest
from polycolab.db.models.catalogue import SqlCatalogueModerator as SqlCatalogueModerator
from polycolab.db.models.catalogue import SqlCatalogueModeratorAudit as SqlCatalogueModeratorAudit
from polycolab.db.models.catalogue import SqlCatalogueRevision as SqlCatalogueRevision
from polycolab.db.models.catalogue import SqlCommunityDeliveryCursor as SqlCommunityDeliveryCursor
from polycolab.db.models.catalogue import SqlExternalAgentCredential as SqlExternalAgentCredential
from polycolab.db.models.catalogue import SqlPublicationComment as SqlPublicationComment
from polycolab.db.models.catalogue import SqlPublicationManifest as SqlPublicationManifest
from polycolab.db.models.catalogue import SqlPublicationProgress as SqlPublicationProgress
from polycolab.db.models.catalogue import SqlPublicationRelation as SqlPublicationRelation
from polycolab.db.models.catalogue import SqlPublicationRevision as SqlPublicationRevision
from polycolab.db.models.catalogue import SqlPublicationSummary as SqlPublicationSummary
from polycolab.db.models.catalogue import SqlPublicRelease as SqlPublicRelease
from polycolab.db.models.catalogue import SqlResearchNotification as SqlResearchNotification
from polycolab.db.models.catalogue import SqlResearchProgressSummary as SqlResearchProgressSummary
from polycolab.db.models.history import SqlExternalAgentIdentity as SqlExternalAgentIdentity
from polycolab.db.models.history import SqlResearchActivityEvent as SqlResearchActivityEvent
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
from polycolab.db.models.platform import SqlContributionEntityLink as SqlContributionEntityLink
from polycolab.db.models.platform import SqlContributionEnvelope as SqlContributionEnvelope
from polycolab.db.models.platform import SqlMutationReceipt as SqlMutationReceipt
from polycolab.db.models.platform import SqlOutboxConsumerReceipt as SqlOutboxConsumerReceipt
from polycolab.db.models.platform import SqlOutboxEvent as SqlOutboxEvent
from polycolab.db.models.projects import SqlInvitation as SqlInvitation
from polycolab.db.models.projects import SqlMembership as SqlMembership
from polycolab.db.models.projects import SqlProject as SqlProject
from polycolab.db.models.research import SqlAttemptEvidenceLink as SqlAttemptEvidenceLink
from polycolab.db.models.research import SqlCorrectionDecision as SqlCorrectionDecision
from polycolab.db.models.research import SqlCorrectionSuggestion as SqlCorrectionSuggestion
from polycolab.db.models.research import SqlCorrespondenceAssessment as SqlCorrespondenceAssessment
from polycolab.db.models.research import SqlHumanNote as SqlHumanNote
from polycolab.db.models.research import SqlHumanNoteRevision as SqlHumanNoteRevision
from polycolab.db.models.research import SqlObjectRevision as SqlObjectRevision
from polycolab.db.models.research import SqlProjectReference as SqlProjectReference
from polycolab.db.models.research import (
    SqlProjectReferenceVersion as SqlProjectReferenceVersion,
)
from polycolab.db.models.research import SqlProofSketchPremise as SqlProofSketchPremise
from polycolab.db.models.research import SqlProofSketchRevision as SqlProofSketchRevision
from polycolab.db.models.research import SqlPublicResearchAnchor as SqlPublicResearchAnchor
from polycolab.db.models.research import SqlRecordModeration as SqlRecordModeration
from polycolab.db.models.research import SqlRecordModerationAudit as SqlRecordModerationAudit
from polycolab.db.models.research import SqlRecordRevision as SqlRecordRevision
from polycolab.db.models.research import SqlRecordStatementLink as SqlRecordStatementLink
from polycolab.db.models.research import SqlRelationAssertion as SqlRelationAssertion
from polycolab.db.models.research import SqlResearchAttachment as SqlResearchAttachment
from polycolab.db.models.research import SqlResearchAttemptRevision as SqlResearchAttemptRevision
from polycolab.db.models.research import SqlResearchComment as SqlResearchComment
from polycolab.db.models.research import SqlResearchObject as SqlResearchObject
from polycolab.db.models.research import SqlResearchProgressUpdate as SqlResearchProgressUpdate
from polycolab.db.models.research import SqlResearchScope as SqlResearchScope
from polycolab.db.models.research import SqlResearchSummary as SqlResearchSummary
from polycolab.db.models.research import SqlResearchSummaryRevision as SqlResearchSummaryRevision
from polycolab.db.models.research import SqlRevisionEndorsement as SqlRevisionEndorsement
from polycolab.db.models.research import SqlStatementRevision as SqlStatementRevision
from polycolab.db.models.research import SqlSummarySourceRevision as SqlSummarySourceRevision
from polycolab.db.models.verification import SqlExecutionClassState as SqlExecutionClassState
from polycolab.db.models.verification import SqlExecutionFairnessState as SqlExecutionFairnessState
from polycolab.db.models.verification import SqlExecutionSlotLease as SqlExecutionSlotLease
from polycolab.db.models.verification import SqlExecutionWorkItem as SqlExecutionWorkItem
from polycolab.db.models.verification import SqlVerificationAttempt as SqlVerificationAttempt
from polycolab.db.models.verification import (
    SqlVerificationEnvironment as SqlVerificationEnvironment,
)
from polycolab.db.models.verification import SqlVerificationEvent as SqlVerificationEvent
from polycolab.db.models.verification import SqlVerificationInput as SqlVerificationInput
from polycolab.db.models.verification import SqlVerificationJob as SqlVerificationJob
from polycolab.db.models.verification import (
    SqlVerificationOutputArtifact as SqlVerificationOutputArtifact,
)
from polycolab.db.models.verification import (
    SqlVerificationReservation as SqlVerificationReservation,
)
from polycolab.db.models.verification import SqlVerificationResult as SqlVerificationResult
from polycolab.entities.enums import AccountTokenPurpose as AccountTokenPurpose
from polycolab.entities.enums import AgentMessageRole as AgentMessageRole
from polycolab.entities.enums import AgentRunEventKind as AgentRunEventKind
from polycolab.entities.enums import AgentRunStatus as AgentRunStatus
from polycolab.entities.enums import AgentSessionStatus as AgentSessionStatus
from polycolab.entities.enums import ArtifactResearchRole as ArtifactResearchRole
from polycolab.entities.enums import ArtifactState as ArtifactState
from polycolab.entities.enums import AttemptEvidenceRole as AttemptEvidenceRole
from polycolab.entities.enums import CanonicalEntityType as CanonicalEntityType
from polycolab.entities.enums import ContributionActorKind as ContributionActorKind
from polycolab.entities.enums import CorrespondenceStatus as CorrespondenceStatus
from polycolab.entities.enums import ExecutionProfile as ExecutionProfile
from polycolab.entities.enums import ExecutionTenantKind as ExecutionTenantKind
from polycolab.entities.enums import ExecutionWorkloadClass as ExecutionWorkloadClass
from polycolab.entities.enums import InvitationStatus as InvitationStatus
from polycolab.entities.enums import MailOutboxStatus as MailOutboxStatus
from polycolab.entities.enums import MailPurpose as MailPurpose
from polycolab.entities.enums import MutationReceiptStatus as MutationReceiptStatus
from polycolab.entities.enums import OutboxEventStatus as OutboxEventStatus
from polycolab.entities.enums import PlatformAgentKind as PlatformAgentKind
from polycolab.entities.enums import ProjectRole as ProjectRole
from polycolab.entities.enums import ProjectVisibility as ProjectVisibility
from polycolab.entities.enums import ProposalChangeStatus as ProposalChangeStatus
from polycolab.entities.enums import ProposalChangeType as ProposalChangeType
from polycolab.entities.enums import ProposalDecisionAction as ProposalDecisionAction
from polycolab.entities.enums import ProvenanceKind as ProvenanceKind
from polycolab.entities.enums import RelationType as RelationType
from polycolab.entities.enums import ResearchEntityClass as ResearchEntityClass
from polycolab.entities.enums import ResearchObjectKind as ResearchObjectKind
from polycolab.entities.enums import ResearchProgressStatus as ResearchProgressStatus
from polycolab.entities.enums import ResearchScopeKind as ResearchScopeKind
from polycolab.entities.enums import RuntimeBindingStatus as RuntimeBindingStatus
from polycolab.entities.enums import RuntimeRunBindingStatus as RuntimeRunBindingStatus
from polycolab.entities.enums import SocialAuthPurpose as SocialAuthPurpose
from polycolab.entities.enums import SocialIdentityAuditAction as SocialIdentityAuditAction
from polycolab.entities.enums import SocialProviderKind as SocialProviderKind
from polycolab.entities.enums import UsageSource as UsageSource
from polycolab.entities.enums import VerificationAttemptState as VerificationAttemptState
from polycolab.entities.enums import VerificationInputRole as VerificationInputRole
from polycolab.entities.enums import VerificationJobState as VerificationJobState
from polycolab.entities.enums import VerificationLanguage as VerificationLanguage
from polycolab.entities.enums import VerificationOutputRole as VerificationOutputRole
from polycolab.entities.enums import VerificationReservationState as VerificationReservationState

__all__ = [
    "SqlAgentLibraryEntry",
    "SqlAgentLibraryDraft",
    "SqlAgentLibraryVersion",
    "SqlAgentLibraryModeration",
    "ProjectRole",
    "ProjectVisibility",
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
    "SqlResearchScope",
    "SqlResearchObject",
    "SqlObjectRevision",
    "SqlRelationAssertion",
    "SqlResearchComment",
    "SqlStatementRevision",
    "SqlRecordRevision",
    "SqlRecordStatementLink",
    "SqlProofSketchRevision",
    "SqlProofSketchPremise",
    "SqlResearchAttemptRevision",
    "SqlAttemptEvidenceLink",
    "SqlHumanNote",
    "SqlHumanNoteRevision",
    "SqlResearchSummary",
    "SqlResearchSummaryRevision",
    "SqlSummarySourceRevision",
    "SqlResearchProgressUpdate",
    "SqlRevisionEndorsement",
    "SqlCorrespondenceAssessment",
    "SqlResearchAttachment",
    "SqlRecordModeration",
    "SqlRecordModerationAudit",
    "SqlCorrectionSuggestion",
    "SqlCorrectionDecision",
    "SqlPublicResearchAnchor",
    "SqlProjectReference",
    "SqlProjectReferenceVersion",
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
    "SqlRunWriteGrant",
    "SqlRunRevisionOutput",
    "SqlRunArtifactOutput",
    "SqlRunToolCapability",
    "SqlProposal",
    "SqlProposalChange",
    "SqlProposalChangeDecision",
    "SqlProposalDecisionBatch",
    "SqlExternalResearchRun",
    "SqlExternalRunInvocation",
    "SqlPublicationManifest",
    "SqlPublicRelease",
    "SqlPublicationRevision",
    "SqlPublicationSummary",
    "SqlPublicationComment",
    "SqlPublicationProgress",
    "SqlPublicationRelation",
    "SqlCatalogueEntry",
    "SqlCatalogueRevision",
    "SqlCatalogueAudit",
    "SqlCommunityDeliveryCursor",
    "SqlResearchNotification",
    "SqlResearchProgressSummary",
    "SqlCatalogueFollow",
    "SqlCatalogueInterest",
    "SqlCatalogueModerator",
    "SqlCatalogueModeratorAudit",
    "SqlExternalAgentCredential",
    "SqlExternalAgentIdentity",
    "SqlResearchActivityEvent",
    "SqlArtifact",
    "SqlArtifactResearchLink",
    "SqlPublicationArtifactMember",
    "SqlVerificationEnvironment",
    "SqlVerificationJob",
    "SqlVerificationInput",
    "SqlVerificationReservation",
    "SqlVerificationAttempt",
    "SqlExecutionWorkItem",
    "SqlExecutionClassState",
    "SqlExecutionFairnessState",
    "SqlExecutionSlotLease",
    "SqlVerificationEvent",
    "SqlVerificationResult",
    "SqlVerificationOutputArtifact",
    "SqlOperatorAccountRecovery",
    "SqlOperatorRestoreInvalidation",
    "SqlContributionEnvelope",
    "SqlContributionEntityLink",
    "SqlMutationReceipt",
    "SqlOutboxEvent",
    "SqlOutboxConsumerReceipt",
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
from polycolab.db.models.reviews import SqlObjectReview as SqlObjectReview
