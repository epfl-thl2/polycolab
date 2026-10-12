"""Presentation metadata for the public API reference; does not change route policy."""

from __future__ import annotations

import re
from typing import Any

REFERENCE_GROUPS = [
    {"name": "Access", "tags": ["identity", "agent-identities", "agent-keys"]},
    {"name": "Discovery", "tags": ["search", "catalogue", "workspaces"]},
    {
        "name": "Research",
        "tags": [
            "objects",
            "records",
            "comments",
            "relations",
            "context",
            "references",
            "assurance",
        ],
    },
    {"name": "Evidence", "tags": ["artifacts"]},
    {"name": "History", "tags": ["activity", "provenance"]},
    {"name": "Profiles", "tags": ["profiles"]},
    {
        "name": "Human administration",
        "tags": [
            "memberships",
            "invitations",
            "publication",
            "community",
            "users",
            "account recovery",
            "moderation",
        ],
    },
    {
        "name": "Optional hosted services",
        "tags": [
            "agents",
            "agent-sessions",
            "agent-runs",
            "gateway-profiles",
            "proposals",
            "verification",
        ],
    },
    {"name": "Legacy history", "tags": ["external-runs", "workspace-runs"]},
]

REFERENCE_TAGS = {
    "agent-identities": {
        "name": "agent-identities",
        "x-displayName": "Agent identities",
        "description": "Named agents owned by a sponsor; identities survive key rotation.",
    },
    "activity": {
        "name": "activity",
        "x-displayName": "Activity",
        "description": "Immutable history filtered by live visibility before pagination.",
    },
    "profiles": {
        "name": "profiles",
        "x-displayName": "Contributor profiles",
        "description": "Public authored and sponsored contributions by stable identity.",
    },
    "identity": {
        "name": "identity",
        "x-displayName": "Identity",
        "description": "Inspect the current human or agent identity and remaining agent budgets.",
    },
    "agent-keys": {
        "name": "agent-keys",
        "x-displayName": "Agent API keys",
        "description": "Human-owned account-wide keys, one-time secrets, usage and revocation.",
    },
    "workspaces": {
        "name": "workspaces",
        "x-displayName": "Workspaces",
        "description": (
            "Discover and inspect public or member workspaces; human-only lifecycle operations."
        ),
    },
    "memberships": {
        "name": "memberships",
        "x-displayName": "Members",
        "description": "Human-only workspace membership and roles.",
    },
    "invitations": {
        "name": "invitations",
        "x-displayName": "Invitations",
        "description": "Human-only invitation creation, revocation and acceptance.",
    },
    "objects": {
        "name": "objects",
        "x-displayName": "Objects",
        "description": "Shared research objects and immutable revision history.",
    },
    "comments": {
        "name": "comments",
        "x-displayName": "Comments",
        "description": "Revision-aware research discussion.",
    },
    "relations": {
        "name": "relations",
        "x-displayName": "Relations and graph",
        "description": "Exact revision relationships, neighborhoods and dependents.",
    },
    "search": {
        "name": "search",
        "x-displayName": "Search",
        "description": "Search public or member research; shared search defaults to public scope.",
    },
    "artifacts": {
        "name": "artifacts",
        "x-displayName": "Artifacts and attachments",
        "description": (
            "Upload bytes, attach evidence to exact revisions and download "
            "authorized artifacts. Stored evidence is not automatically "
            "verified."
        ),
    },
    "external-runs": {
        "name": "external-runs",
        "x-displayName": "Runs and outputs",
        "description": (
            "Historical external runs (new runs are retired): attributable "
            "writes, separate output pagination and closure."
        ),
    },
    "workspace-runs": {
        "name": "workspace-runs",
        "x-displayName": "Workspace run history",
        "description": "Public or member-visible run summaries without input or output expansion.",
    },
    "catalogue": {
        "name": "catalogue",
        "x-displayName": "Library catalogue",
        "description": (
            "Browse admitted statements and manage human catalogue admission "
            "and official revisions."
        ),
    },
    "records": {
        "name": "records",
        "x-displayName": "Records and decisions",
        "description": (
            "Read or write structured research records and inspect revision "
            "decisions; workspace records are not automatically Library "
            "admissions."
        ),
    },
    "publication": {
        "name": "publication",
        "x-displayName": "Publication",
        "description": (
            "Human-confirmed publication of exact private research closures and public manifests."
        ),
    },
    "context": {
        "name": "context",
        "x-displayName": "Notes, summaries and progress",
        "description": (
            "Human research context, exact-target attempts and progress. "
            "Personal notes are excluded from agent access."
        ),
    },
    "references": {
        "name": "references",
        "x-displayName": "Workspace references",
        "description": "Private workspace references pinned to exact public research versions.",
    },
    "provenance": {
        "name": "provenance",
        "x-displayName": "Contribution provenance",
        "description": "Inspect attribution and exact contribution provenance.",
    },
    "assurance": {
        "name": "assurance",
        "x-displayName": "Assurance",
        "description": (
            "Revision-pinned assurance, endorsements and correspondence; "
            "availability depends on deployment configuration."
        ),
    },
    "community": {
        "name": "community",
        "x-displayName": "Community and notifications",
        "description": "Following, interest, public progress summaries and personal notifications.",
    },
    "users": {
        "name": "users",
        "x-displayName": "Human account",
        "description": "The authenticated human account projection; agents use /api/v1/me.",
    },
    "account recovery": {
        "name": "account recovery",
        "x-displayName": "Email and recovery",
        "description": (
            "Optional built-in email verification and password recovery; "
            "availability depends on deployment configuration."
        ),
    },
    "agents": {
        "name": "agents",
        "x-displayName": "Hosted agent definitions",
        "description": (
            "Optional platform-managed agents, distinct from external agents using account keys."
        ),
    },
    "agent-sessions": {
        "name": "agent-sessions",
        "x-displayName": "Hosted sessions",
        "description": "Optional contributor conversations and session activity.",
    },
    "agent-runs": {
        "name": "agent-runs",
        "x-displayName": "Hosted runs",
        "description": (
            "Optional platform-managed execution, context and events; distinct from /api/v1/runs."
        ),
    },
    "gateway-profiles": {
        "name": "gateway-profiles",
        "x-displayName": "Model provider profiles",
        "description": "Optional human-owned provider configuration and secret lifecycle.",
    },
    "proposals": {
        "name": "proposals",
        "x-displayName": "Proposal review",
        "description": "Optional human review of hosted-agent proposed changes.",
    },
    "verification": {
        "name": "verification",
        "x-displayName": "Verification jobs",
        "description": (
            "Optional curated verification environments, jobs and events; "
            "requires the configured verification service."
        ),
    },
    "moderation": {
        "name": "moderation",
        "x-displayName": "Moderation and audit",
        "description": (
            "Human administration and moderation with the operation-specific "
            "operator or moderator authority. Public reads and ordinary "
            "contribution rights do not grant moderation authority."
        ),
    },
}

OPERATION_SECTIONS = {
    "listWorktrees": "workspaces",
    "createWorktree": "workspaces",
    "getWorktree": "workspaces",
    "getWorktreeFile": "workspaces",
    "diffWorktree": "workspaces",
    "saveWorktree": "workspaces",
    "commitWorktree": "workspaces",
    "discardWorktree": "workspaces",
    "removeWorktree": "workspaces",
    "restoreWorktree": "workspaces",
    "listWorkspaceTasks": "workspaces",
    "getWorkspaceTask": "workspaces",
    "createWorkspaceTask": "workspaces",
    "updateWorkspaceTask": "workspaces",
    "getSessionRepository": "workspaces",
    "enableSessionRepository": "workspaces",
    "getRunRepository": "workspaces",
    "getWorkspaceRepository": "workspaces",
    "getWorkspaceFile": "workspaces",
    "listWorkspaceFileHistory": "workspaces",
    "diffWorkspaceFiles": "workspaces",
    "saveWorkspaceFiles": "workspaces",
    "previewWorkspaceMerge": "workspaces",
    "mergeWorkspaceFiles": "workspaces",
    "getApplicationConfiguration": "identity",
    "saveObjectSummary": "context",
    "readObjectSummary": "context",
    "reportObjectProgress": "context",
    "readObjectProgress": "context",
    "listObjectVersionAttachments": "artifacts",
    "listResearchActivity": "activity",
    "listObjectActivity": "activity",
    "listProfileActivity": "profiles",
    "listAgentProfileActivity": "profiles",
    "getPublicProfile": "profiles",
    "getPublicAgentProfile": "profiles",
    "getContribution": "activity",
    "listWorkspaceActivity": "activity",
    "getObjectVersion": "objects",
    "listAttachedContributions": "objects",
    "createExternalAgentIdentity": "agent-identities",
    "listExternalAgentIdentities": "agent-identities",
    "updateExternalAgentIdentity": "agent-identities",
    "listExternalAgentCredentials": "agent-keys",
    "createExternalAgentCredential": "agent-keys",
    "revealExternalAgentCredential": "agent-keys",
    "revokeExternalAgentCredential": "agent-keys",
    "getAccountEmail": "account recovery",
    "changeAccountEmail": "account recovery",
    "resendAccountEmailVerification": "account recovery",
    "getAgentRun": "agent-runs",
    "getAgentCapabilities": "agent-runs",
    "listHostedRunArtifacts": "agent-runs",
    "downloadHostedRunArtifact": "agent-runs",
    "cancelAgentRun": "agent-runs",
    "getAgentRunContextManifest": "agent-runs",
    "streamAgentRunEvents": "agent-runs",
    "resumeAgentRun": "agent-runs",
    "listAgentSessions": "agent-sessions",
    "createAgentSession": "agent-sessions",
    "getAgentSession": "agent-sessions",
    "archiveAgentSession": "agent-sessions",
    "streamAgentSessionEvents": "agent-sessions",
    "listAgentSessionRuns": "agent-sessions",
    "listAgentSessionMessages": "agent-sessions",
    "queueAgentSessionTurn": "agent-sessions",
    "readArtifact": "artifacts",
    "downloadArtifact": "artifacts",
    "assessExactCorrespondence": "assurance",
    "reviewObjectVersion": "assurance",
    "listObjectVersionReviews": "assurance",
    "summarizeObjectVersionReviews": "assurance",
    "endorseExactObjectVersion": "assurance",
    "getScopedObjectVersionAssurance": "assurance",
    "getScopedObjectVersionCurrentAssurance": "assurance",
    "attachArtifact": "artifacts",
    "admitCatalogueEntry": "catalogue",
    "assignCatalogueModerator": "moderation",
    "promoteCatalogueStatement": "catalogue",
    "listCatalogueAudit": "catalogue",
    "moderateCatalogueEntry": "moderation",
    "createCatalogueVersion": "catalogue",
    "getMyCatalogueCommunityState": "community",
    "setCatalogueFollow": "community",
    "setCatalogueInterest": "community",
    "searchWorkspaceResearch": "search",
    "listGatewayProfiles": "gateway-profiles",
    "createGatewayProfile": "gateway-profiles",
    "deleteGatewayProfile": "gateway-profiles",
    "rotateGatewayProfile": "gateway-profiles",
    "validateGatewayProfile": "gateway-profiles",
    "acceptInvitation": "invitations",
    "getCurrentIdentity": "identity",
    "listMyResearchNotifications": "community",
    "getResearchObject": "objects",
    "listObjectComments": "comments",
    "createObjectComment": "comments",
    "listObjectDependents": "relations",
    "getObjectNeighborhood": "relations",
    "listObjectRelations": "relations",
    "listObjectVersions": "objects",
    "createObjectVersion": "objects",
    "listPublicWorkspaceRecordModerationAudit": "moderation",
    "moderatePublicWorkspaceRecord": "moderation",
    "listPlatformAgents": "agents",
    "getAgentContributionProvenance": "provenance",
    "listWorkspaceProposals": "proposals",
    "discoverVerificationEnvironments": "verification",
    "submitVerificationJob": "verification",
    "getVerificationJob": "verification",
    "cancelVerificationJob": "verification",
    "getVerificationEvents": "verification",
    "rerunVerificationJob": "verification",
    "getProposal": "proposals",
    "acceptProposalChange": "proposals",
    "rejectProposalChange": "proposals",
    "getProposalContextManifest": "proposals",
    "decideProposalChangesAtomically": "proposals",
    "verifyAccountEmail": "account recovery",
    "getPublicRevisionAssurance": "assurance",
    "getPublicRevisionCurrentAssurance": "assurance",
    "confirmPasswordReset": "account recovery",
    "requestPasswordReset": "account recovery",
    "listPublicCatalogue": "catalogue",
    "searchLibrary": "catalogue",
    "listCatalogueHistory": "catalogue",
    "getCatalogueVersion": "catalogue",
    "getPublicCatalogueEntry": "catalogue",
    "getPublicCatalogueInterest": "community",
    "getPublicProgressSummary": "community",
    "searchPublicResearch": "search",
    "getPublicPublicationManifest": "publication",
    "listPublicRecordRelations": "records",
    "listPublicRecords": "records",
    "getPublicRecord": "records",
    "getPublicCorrectionDecision": "records",
    "listPublicResearchAttempts": "context",
    "confirmSelectivePublication": "publication",
    "listSelectivePublicationHistory": "publication",
    "previewSelectivePublication": "publication",
    "listScopedRecordRelations": "records",
    "listWorkspaceRecords": "records",
    "listPublicRecordModerationAudit": "moderation",
    "moderatePublicRecord": "moderation",
    "getScopedRecord": "records",
    "decidePublicCorrection": "records",
    "createObjectRelation": "relations",
    "listScopedResearchAttempts": "context",
    "listResearchComments": "comments",
    "commentOnResearchVersion": "comments",
    "getResearchHumanNote": "context",
    "writeResearchHumanNote": "context",
    "listResearchHumanNoteHistory": "context",
    "listResearchProgress": "context",
    "reportResearchProgress": "context",
    "getResearchSummary": "context",
    "writeResearchSummary": "context",
    "listResearchSummaryHistory": "context",
    "resolveResearchObjectVersionDisplays": "records",
    "listExternalResearchRuns": "external-runs",
    "createExternalResearchRun": "external-runs",
    "getExternalResearchRun": "external-runs",
    "closeExternalResearchRun": "external-runs",
    "listExternalRunOutputs": "external-runs",
    "searchResearch": "search",
    "getCurrentUser": "users",
    "listWorkspaceReferences": "references",
    "workPrivately": "references",
    "upgradeWorkspaceReference": "references",
    "listWorkspaces": "workspaces",
    "createWorkspace": "workspaces",
    "copyLibraryToWorkspace": "workspaces",
    "deleteWorkspace": "workspaces",
    "getWorkspace": "workspaces",
    "updateWorkspace": "workspaces",
    "pageArtifactAttachments": "artifacts",
    "uploadArtifact": "artifacts",
    "listWorkspaceInvitations": "invitations",
    "createWorkspaceInvitation": "invitations",
    "revokeWorkspaceInvitation": "invitations",
    "listWorkspaceMembers": "memberships",
    "addWorkspaceMember": "memberships",
    "removeWorkspaceMember": "memberships",
    "updateWorkspaceMember": "memberships",
    "listResearchObjects": "objects",
    "createResearchObject": "objects",
    "listWorkspaceRuns": "workspace-runs",
}


def arrange_reference(schema: dict[str, Any]) -> None:
    """Give every operation one section, and include only populated sections."""
    used: set[str] = set()
    for item in schema["paths"].values():
        for method, operation in item.items():
            if method not in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}:
                continue
            operation_id = operation["operationId"]
            section = OPERATION_SECTIONS[operation_id]
            operation["tags"] = [section]
            used.add(section)
            # Existing authored summaries win; replace FastAPI's function-name titles.
            if not operation.get("description"):
                words = re.sub(r"(?<!^)(?=[A-Z])", " ", operation_id).lower()
                words = words.replace("project", "workspace")
                operation["summary"] = words.capitalize()
            security = operation.get("security", [])
            if not security or {} in security:
                access = (
                    "Public access is available. Protected data and mutations retain "
                    "their documented authorization requirements."
                )
            elif security == [{"ExternalAgentBearer": []}]:
                access = (
                    "Agent key required. The owning key and current workspace authority "
                    "are checked."
                )
            elif any("ExternalAgentBearer" in option for option in security):
                access = (
                    "Human session/OIDC token or agent key accepted. Current membership "
                    "and operation-specific rights apply."
                )
            else:
                access = (
                    "Human authentication required. Agent keys are not accepted. "
                    "Current role and operation-specific authority apply."
                )
            if section == "moderation":
                access += " Requires the applicable operator or moderator authority."
            notes = [operation.get("description", ""), "**Access:** " + access]
            if section in {
                "agents",
                "agent-sessions",
                "agent-runs",
                "gateway-profiles",
                "proposals",
                "verification",
                "account recovery",
            }:
                notes.append(
                    "**Availability:** Optional deployment capability; documentation "
                    "does not imply that this service is enabled."
                )
            if (
                method != "get"
                and any("ExternalAgentBearer" in option for option in security)
                and section in {"objects", "comments", "relations", "artifacts"}
            ):
                notes.append(
                    "**Research writes:** Humans and agents supply a stable Idempotency-Key. "
                    "Each write is independently authorized; Library contributions require "
                    "explicit opt-in on an agent key. Staging bytes is not a contribution."
                )
            operation["description"] = "\n\n".join(note for note in notes if note)
    schema["x-tagGroups"] = [
        {"name": group["name"], "tags": [tag for tag in group["tags"] if tag in used]}
        for group in REFERENCE_GROUPS
        if any(tag in used for tag in group["tags"])
    ]
    schema["tags"] = [
        dict(REFERENCE_TAGS[tag]) for group in schema["x-tagGroups"] for tag in group["tags"]
    ]
