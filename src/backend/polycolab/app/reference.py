"""Presentation metadata for the public API reference; does not change route policy."""

from __future__ import annotations

import re
from typing import Any

REFERENCE_GROUPS = [
    {"name": "Access", "tags": ["identity", "agent-keys"]},
    {"name": "Projects", "tags": ["projects", "library"]},
    {"name": "Artifacts", "tags": ["artifacts"]},
    {
        "name": "Human administration",
        "tags": ["memberships", "invitations", "account", "account recovery"],
    },
    {
        "name": "Optional hosted services",
        "tags": ["agents", "conversations", "runs", "provider-connections", "research-helper"],
    },
]

REFERENCE_TAGS = {
    "research-helper": {
        "name": "research-helper",
        "x-displayName": "Research helper",
        "description": (
            "Private, text-only assistance using the authenticated user's provider connection."
        ),
    },
    "library": {
        "name": "library",
        "x-displayName": "Agent library",
        "description": "Public prompts, skills and plugin listings with human-owned drafts.",
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
    "projects": {
        "name": "projects",
        "x-displayName": "Projects",
        "description": "Discover and inspect public or member projects; human-only "
        "lifecycle operations.",
    },
    "memberships": {
        "name": "memberships",
        "x-displayName": "Members",
        "description": "Human-only project membership and roles.",
    },
    "invitations": {
        "name": "invitations",
        "x-displayName": "Invitations",
        "description": "Human-only invitation creation, revocation and acceptance.",
    },
    "artifacts": {
        "name": "artifacts",
        "x-displayName": "Artifacts and attachments",
        "description": "Upload bytes, attach evidence to exact revisions and download "
        "authorized artifacts. Stored evidence is not automatically "
        "verified.",
    },
    "account": {
        "name": "account",
        "x-displayName": "Human account",
        "description": "The authenticated human account projection; agents use /api/v1/me.",
    },
    "account recovery": {
        "name": "account recovery",
        "x-displayName": "Email and recovery",
        "description": "Optional built-in email verification and password "
        "recovery; availability depends on deployment "
        "configuration.",
    },
    "agents": {
        "name": "agents",
        "x-displayName": "Hosted agent definitions",
        "description": "Optional platform-managed agents, distinct from external agents "
        "using account keys.",
    },
    "conversations": {
        "name": "conversations",
        "x-displayName": "Conversations",
        "description": (
            "Saved project conversations, shared participation, and read-only history."
        ),
    },
    "runs": {
        "name": "runs",
        "x-displayName": "Hosted runs",
        "description": "Conversation runs scoped to the user and project permissions.",
    },
    "provider-connections": {
        "name": "provider-connections",
        "x-displayName": "Provider connections",
        "description": "Optional human-owned provider configuration and secret lifecycle.",
    },
}

OPERATION_SECTIONS = {
    "askResearchHelper": "research-helper",
    "listLibrary": "library",
    "listOwnedLibrary": "library",
    "createLibraryItem": "library",
    "getLibraryDraft": "library",
    "updateLibraryDraft": "library",
    "publishLibraryItem": "library",
    "copyLibraryItem": "library",
    "archiveLibraryItem": "library",
    "getLibraryModerationState": "library",
    "moderateLibraryItem": "library",
    "getLibraryItem": "library",
    "listLibraryVersions": "library",
    "getLibraryVersion": "library",
    "downloadLibrarySkill": "library",
    "previewCollaborativeConversion": "projects",
    "convertProjectToCollaborative": "projects",
    "setConversationSharing": "conversations",
    "listAgentChanges": "projects",
    "retryChangeSet": "projects",
    "resolveChangeSet": "projects",
    "revertChangeSet": "projects",
    "diffCollaborativeCheckpoint": "projects",
    "getBasicFiles": "projects",
    "changeBasicFiles": "projects",
    "getCollaborativeProject": "projects",
    "getCollaborativeFile": "projects",
    "changeCollaborativeFiles": "projects",
    "getCollaborativeHistory": "projects",
    "listCollaborativeCheckpoints": "projects",
    "createCollaborativeCheckpoint": "projects",
    "getCollaborativeCheckpointFiles": "projects",
    "restoreCollaborativeCheckpoint": "projects",
    "createLatexBuild": "projects",
    "listLatexBuilds": "projects",
    "getLatexBuild": "projects",
    "cancelLatexBuild": "projects",
    "downloadLatexOutput": "projects",
    "listWorktrees": "projects",
    "getWorktree": "projects",
    "createWorktree": "projects",
    "updateWorktree": "projects",
    "getWorktreeFile": "projects",
    "diffWorktree": "projects",
    "saveWorktree": "projects",
    "commitWorktree": "projects",
    "discardWorktree": "projects",
    "removeWorktree": "projects",
    "restoreWorktree": "projects",
    "getConversationRepository": "projects",
    "enableConversationRepository": "projects",
    "getRunRepository": "projects",
    "getProjectRepository": "projects",
    "getProjectFile": "projects",
    "listProjectFileHistory": "projects",
    "diffProjectFiles": "projects",
    "saveProjectFiles": "projects",
    "previewProjectMerge": "projects",
    "mergeProjectFiles": "projects",
    "getApplicationConfiguration": "identity",
    "listAgentApiKeys": "agent-keys",
    "createAgentApiKey": "agent-keys",
    "revealAgentApiKey": "agent-keys",
    "revokeAgentApiKey": "agent-keys",
    "getAccountEmail": "account recovery",
    "changeAccountEmail": "account recovery",
    "resendAccountEmailVerification": "account recovery",
    "getRun": "runs",
    "getAgentCapabilities": "runs",
    "listHostedRunArtifacts": "runs",
    "downloadHostedRunArtifact": "runs",
    "resumeRun": "runs",
    "listConversations": "conversations",
    "createConversation": "conversations",
    "getConversation": "conversations",
    "getConversationSharing": "conversations",
    "listChildConversations": "conversations",
    "updateConversation": "conversations",
    "streamConversation": "conversations",
    "listConversationRuns": "conversations",
    "listConversationItems": "conversations",
    "submitConversationEvent": "conversations",
    "readArtifact": "artifacts",
    "downloadArtifact": "artifacts",
    "listProviderConnections": "provider-connections",
    "createProviderConnection": "provider-connections",
    "deleteProviderConnection": "provider-connections",
    "rotateProviderConnection": "provider-connections",
    "validateProviderConnection": "provider-connections",
    "acceptInvitation": "invitations",
    "getCurrentIdentity": "identity",
    "listPlatformAgents": "agents",
    "verifyAccountEmail": "account recovery",
    "confirmPasswordReset": "account recovery",
    "requestPasswordReset": "account recovery",
    "getAccount": "account",
    "chooseUsername": "account",
    "listProjects": "projects",
    "createProject": "projects",
    "deleteProject": "projects",
    "getProject": "projects",
    "updateProject": "projects",
    "uploadArtifact": "artifacts",
    "listProjectInvitations": "invitations",
    "createProjectInvitation": "invitations",
    "revokeProjectInvitation": "invitations",
    "listProjectMembers": "memberships",
    "addProjectMember": "memberships",
    "removeProjectMember": "memberships",
    "updateProjectMember": "memberships",
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
                words = words.replace("project", "project")
                operation["summary"] = words.capitalize()
            security = operation.get("security", [])
            if not security or {} in security:
                access = (
                    "Public access is available. Protected data and mutations retain "
                    "their documented authorization requirements."
                )
            elif security == [{"ExternalAgentBearer": []}]:
                access = (
                    "Agent API key required. The owning key and current project "
                    "authority are checked."
                )
            elif any("ExternalAgentBearer" in option for option in security):
                access = (
                    "Human session/OIDC token or agent API key accepted. Current membership "
                    "and operation-specific rights apply."
                )
            else:
                access = (
                    "Human authentication required. Agent API keys are not accepted. "
                    "Current role and operation-specific authority apply."
                )
            if section == "moderation":
                access += " Requires the applicable operator or moderator authority."
            notes = [operation.get("description", ""), "**Access:** " + access]
            if section in {
                "agents",
                "conversations",
                "runs",
                "provider-connections",
                "account recovery",
            }:
                notes.append(
                    "**Availability:** Optional deployment capability; documentation "
                    "does not imply that this service is enabled."
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
