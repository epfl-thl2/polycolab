# Product terminology

Use one name for each concept across the browser, API, application, and database.
UI shorthand is permitted where its meaning is clear.

| Concept                                            | Canonical term            | UI wording                    |
| -------------------------------------------------- | ------------------------- | ----------------------------- |
| Shared collaboration resource                      | Project                   | Project                       |
| Saved exchange and history                         | Conversation              | Chat                          |
| User input and ensuing agent work                  | Turn                      | Turn                          |
| One execution attempt, including a resumed attempt | Run                       | Run                           |
| Agent software such as Codex or Claude Code        | Agent harness             | Agent                         |
| Sandbox or container executing agent software      | Execution environment     | Execution environment         |
| Person using the service                           | User                      | User                          |
| Login and personal settings                        | Account                   | Account                       |
| Credential for external agent access               | Agent API key             | Agent API key                 |
| Person owning an agent API key                     | API key owner             | Owner                         |
| Person submitting hosted execution                 | Requesting user           | Requested by                  |
| User whose authority an actor delegates            | Delegating user           | Not exposed                   |
| Project roles                                      | Owner, Editor, Viewer     | Owner, Editor, Viewer         |
| File mode                                          | Basic, Collaborative, Git | Basic, Collaborative, Git     |
| Saved model endpoint and credentials               | Provider connection       | Provider connection           |
| Reusable instruction collection                    | Library                   | Library, My library           |
| Reusable prompt, skill, or plugin listing          | Library item              | Prompt, Skill, Plugin listing |
| Grouped agent file edits                           | Change set                | Agent changes                 |
| Durable duplicate-operation result                 | Idempotency record        | Not exposed                   |
| Queued execution                                   | Execution job             | Job                           |
| User/project scheduling allocation boundary        | Scheduling scope          | Not exposed                   |
| Final usage accounting                             | Usage reconciliation      | Usage                         |
| Maximum counted write operations                   | Write limit               | Write limit                   |

Authentication sessions and harness runtime sessions are distinct from conversations.
A resumed run is a new attempt; previous runs remain historical records. A turn is
descriptive vocabulary, not an additional persisted resource.

Project visibility describes metadata discovery. Conversation access is separately
Private, Members can view, or Members can participate. Public metadata does not
grant file access. Project and conversation ownership are distinct.

Keep precise technical terms: actor, principal, grant, capability, worker, executor,
controller, scheduler, lease, artifact, snapshot, checkpoint, commit, and worktree.
Use Attachment or Output file for an artifact only when that describes its purpose.
A workspace is an agent's working environment, not a synonym for a project.

Historical migrations, immutable event payloads, idempotency identities, encrypted
credential contexts, storage paths, and external protocols can retain historical
names. Their compatibility readers must identify those exceptions explicitly.
Do not rewrite historical data solely to change its wording.
