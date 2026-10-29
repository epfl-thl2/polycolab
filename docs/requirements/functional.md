# Functional requirements

A project is the shared workspace for human and agent work. Members can browse files, edit within their role, and work with project conversations.

- Accounts support sign-in, provider credentials, named external agents, and revocable agent keys.
- Owners manage project metadata, visibility, membership, and lifecycle. Contributors can write files; read-only members can read. Archived projects prevent writes.
- Default projects use current server files with digest-guarded updates. Git projects retain worktrees and explicit commits. Linear projects retain live collaboration and checkpoints.
- Hosted agent sessions retain private or explicitly shared conversations, bounded execution, run history, cancellation, and output artifacts.
- Project artifacts store verified bytes and require current project access. Hosted exports retain session-specific access restrictions.
- LaTeX builds operate on saved project files and retain private PDFs and logs.
- The independent agent library stores reusable prompts, skills, and plugin listings. Direct provider chat remains a separate API capability.

Research records, immutable research revisions, relationship graphs, commons, statement catalogue, research publication, review proposals, verification jobs, and contribution profiles are outside the product. They have no APIs or browser surfaces.
