# Functional requirements

A project is the shared workspace for human and agent work. Members can browse files, edit within their role, and work with project conversations.

- Accounts support sign-in, provider credentials, and directly owned revocable agent API keys.
- Owners manage project metadata, visibility, membership, and lifecycle. Editors can write files; viewers can read. Archived projects prevent writes.
- Basic projects use current server files with digest-guarded updates. Git projects retain worktrees and explicit commits. Collaborative projects retain live collaboration and checkpoints.
- Hosted agent conversations retain private or explicitly shared conversations, bounded execution, run history, cancellation, and output artifacts.
- Project artifacts store verified bytes and require current project access. Hosted exports retain conversation-specific access restrictions.
- LaTeX builds operate on saved project files and retain private PDFs and logs.
- The independent agent library stores reusable prompts, skills, and plugin listings. Direct provider histories remain readable through the conversation API; direct inference is retired.

Research records, immutable research revisions, relationship graphs, commons, statement catalogue, research publication, review proposals, verification jobs, and contribution profiles are outside the product. They have no APIs or browser surfaces.

## Shared conversations

- One saved conversation contains its transcript and execution history.
  Agent configuration is pinned at creation; provider selection is explicit per message.
- New conversations require a project and editor or owner membership.
  Retired direct-provider histories remain readable, including standalone histories,
  and permit title and archive changes without execution or expanded sharing.
- Conversation owners choose Private, Members can view, or Members can participate access.
  Private conversations remain owner-only, including against other project owners.
  Members can view admits current members; Members can participate additionally allows
  current editors and owners to submit messages using their own provider connections,
  credentials, quotas, and attributable execution authority.
- The conversation owner controls title, archival, and sharing and may interrupt any run.
  A participant may interrupt their own run. Interruptions identify an exact run;
  they never implicitly cancel a successor.
- Sharing previews cover the entire user-visible transcript and future messages.
  Private prompts, runtime identifiers, model-only context, sensitive tool content,
  and private artifacts are excluded. Membership revocation ends shared access.
- Parent and child conversations retain independent access controls. Child sharing defaults
  to private, and knowing a related conversation ID grants no access.
  Hierarchy references preserve one project and root tree; parentage is immutable.
