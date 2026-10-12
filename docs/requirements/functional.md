# Functional requirements

These requirements describe core product behavior.
They apply to the browser and authorized agent clients.
Implementation status belongs in the [architecture](../architecture/README.md) and [roadmap](../roadmap.md).

## Accounts and workspaces

- Anyone can read public research without signing in.
- Signed-in users can create workspaces and become their owners.
- New workspaces default to public, with an explicit private option.
- Owners can manage visibility and membership, while preserving at least one owner.
- Owners and contributors can develop research.
  Read-only members can inspect shared work.
- Private workspace access follows current membership and permissions.

## Workspace working files

Workspace members can browse saved working files and their commit history.
Contributors and owners can save shared files; read-only members cannot mutate
them. These files stay members-only even when workspace research is public.
Working files supplement SQL research records; saving or merging files does not
publish research or revise a research object.

Humans edit real Git worktrees. Save persists uncommitted files without advancing
HEAD; Commit changes records all saved changes after diff review and a required
message. Discard changes requires confirmation. A stale
save must preserve the browser draft and require comparison with the newer
version. The browser organizes work by Main and named worktrees, with private
conversations nested under each. Contributors and owners can create a worktree
from a selected branch (Main by default) without starting a conversation. Selecting a worktree switches its saved
files into Explorer; new conversations belong to the selected worktree. Existing
saved branches and conversations remain accessible. Conversation titles and
content remain private to their existing owners.

Hosted runs receive a disposable checkout pinned to HEAD and the saved revision.
Successful outputs remain uncommitted for human review. Runs sharing any worktree,
including Main, execute serially. Queued and active runs block human writes.
Removing a worktree retains its branch, metadata, and private conversations; dirty
removal requires confirmation, and Main cannot be removed. Missing checkouts must
be shown as unavailable. Restoring an active missing checkout retains saved work.
Humans review and merge changes, resolving conflicting files explicitly.

The initial implementation uses bounded source files and small inputs. Large
outputs remain artifacts. Character-by-character coediting, presence, external
Git access, and a new multi-agent scheduler are deferred. See the
[implementation and operational contract](../architecture/workspace-files.md).

## Research records and references

- Researchers can create statements, definitions, claims, proof sketches, attempts, and counterexamples with mathematical text.
- Each object has its own identity, authorship, and saved revision history.
- Researchers can edit objects and inspect earlier revisions.
  Conflicting edits must not overwrite newer work silently.
- Relationships identify the exact revisions they connect, including public sources used in private workspaces.
- Lists, search, filters, and a relationship map help researchers find and inspect accessible work.
- Objects support notes, authored summaries, comments, progress, and independently saved attempts.
- A dedicated human note belongs to its owner.
  Agents and other contributors cannot overwrite it.
- A proof sketch identifies its exact conclusion and required premises.
  Alternative sketches remain separate objects.
- An attempt identifies the exact object revision it investigates.
  Failed attempts remain findable, even without a resulting edit.
- Derived summaries link to their sources and show when they are stale.
- Authorized workspace users can delete and restore research objects.
  Deletion preserves history and existing references.
  It does not delete related research or withdraw published copies.

## Public commons

- Public Library entries expose statements, assumptions, supporting sources or review, status, and revision history.
- Signed-in humans can admit entries under the [Library admission rules](library.md#admission-and-status), without mandatory pre-review.
- Humans and authorized agents can contribute supporting research to existing public statements.
- Authors and moderators maintain official Library revisions.
  Other contributors can suggest corrections.
- Humans can follow entries and cast or withdraw an interest vote.
  Neither action certifies correctness.
- Moderators can hide abusive content while retaining reasons and history.

## Conversations and agents

- Researchers can start, find, and resume private conversations with an assistant.
- Researchers choose the research context available to the assistant.
- The interface connects saved outputs to the research objects and revisions they use or create.
- Researchers can inspect execution state, cancel work, and recover from interruption when possible.
- Authorized agents can save scoped contributions directly.
  Agent identity and sponsoring human remain visible in attribution.
- Changes outside an agent's editing authority remain suggestions.
- Where review applies, a human can accept, edit and accept, or reject individual suggestions.
- A selected batch applies together or fails together.
  Stale suggestions require conflict resolution.
- External agents can read and contribute through the shared HTTPS API within their permissions.
- Researchers can manage agent keys and their own model-provider connections.

## Formalization and computation

- A statement can have multiple Lean formalizations with source, declarations, assumptions, and check results.
- Python computations retain code, inputs, environment, outputs, and rerun information.
- Authorized humans and agents can submit, inspect, cancel, and rerun bounded jobs.
- Results identify the exact research revisions and inputs checked.
  Later edits do not inherit earlier assurance.
- Compilation, complete proof checking, correspondence to an informal statement, and computational support remain distinguishable.
- Computational evidence explains what it supports.
  Successful execution alone does not establish truth.

## Collaboration and publication

- Collaborators can inspect shared research, discuss it, and develop separate approaches.
- Private conversations remain private unless the user explicitly shares their content as research.
- An authorized human can select exact private records to publish and preview the result.
- Required dependencies must already be public or included in the publication.
- Publication preserves origin and authorship while excluding private conversations, dedicated personal notes, and secrets.
- Comments and summaries are published only when explicitly selected.
- Copying a Library entry follows the [Library copy rules](library.md#discovery-and-development).
