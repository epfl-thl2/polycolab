# Functional requirements

A project is the shared workspace for human and agent work. Members can browse files, edit within their role, and work with project conversations.

- Accounts support sign-in, provider credentials, and directly owned revocable agent keys.
- Owners manage project metadata, visibility, membership, and lifecycle. Contributors can write files; read-only members can read. Archived projects prevent writes.
- Default projects use current server files with digest-guarded updates. Git projects retain worktrees and explicit commits. Linear projects retain live collaboration and checkpoints.
- Hosted agent sessions retain private or explicitly shared conversations, bounded execution, run history, cancellation, and output artifacts.
- Project artifacts store verified bytes and require current project access. Hosted exports retain session-specific access restrictions.
- LaTeX builds operate on saved project files and retain private PDFs and logs.
- The independent agent library stores reusable prompts, skills, and plugin listings. Direct provider histories remain readable through the session API; direct inference is retired.

Research records, immutable research revisions, relationship graphs, commons, statement catalogue, research publication, review proposals, verification jobs, and contribution profiles are outside the product. They have no APIs or browser surfaces.

## Shared sessions

- One saved session identifies its conversation, transcript, and execution history.
  Agent configuration is pinned at creation; provider selection is explicit per message.
- New sessions require a project and contributor or owner membership.
  Retired direct-provider histories remain readable, including standalone histories,
  and permit title and archive changes without execution or expanded sharing.
- Session owners choose private, project-readable, or project-contributable sharing.
  Private sessions remain owner-only, including against other project owners.
  Readable sessions admit current members; contributable sessions additionally allow
  current contributors and owners to submit messages using their own provider connections,
  credentials, quotas, and attributable execution authority.
- The session owner controls title, archival, and sharing and may interrupt any run.
  A contributor may interrupt their own run. Interruptions identify an exact run;
  they never implicitly cancel a successor.
- Sharing previews cover the entire user-visible transcript and future messages.
  Private prompts, runtime identifiers, model-only context, sensitive tool content,
  and private artifacts are excluded. Membership revocation ends shared access.
- Parent and child sessions retain independent access controls. Child sharing defaults
  to private, and knowing a related session ID grants no access.
  Hierarchy references preserve one project and root tree; parentage is immutable.
