# Project files and Git worktrees

Each project has one managed bare Git repository at
`<PROJECT_REPOSITORY_DIRECTORY>/<project UUID>.git`. Native linked checkouts live
alongside it at `<project UUID>.worktrees/<worktree UUID>`. These directories share
one persistent server filesystem; Docker keeps them in the repository volume.
Git owns branches, commits, indexes, and file contents. SQL owns membership,
worktree names, creator attribution, lifecycle, private conversations, run bindings,
and operation receipts. Repository content is member-only even for public projects.

## Worktrees and collaboration

The browser presents Project → Worktrees → Conversations. Main and named worktrees
are shared by project members; owners and contributors can edit, and readers can
inspect. Conversations remain creator-private. Worktrees have no ownership groups.
Creating a worktree asks for a name, a unique branch name, and a starting branch
(default Main). One managed linked checkout is allowed per branch. The service
uses Git's worktree inventory to verify availability; missing checkouts are shown
as unavailable rather than healthy metadata entries.

Save persists an uncommitted file snapshot without advancing the branch's HEAD.
Source control lists added, modified, and deleted saved files. Review & commit
shows the full shared diff and requires a commit message. Commit changes commits
all saved changes. Unsaved editor drafts are excluded only after explicit
confirmation. Discard changes restores the saved files to HEAD after confirmation.
Update from Main and merge review require both working directories to be clean.
The existing three-way merge and explicit conflict-resolution workflow is retained.

The editor keeps drafts and tabs in memory per worktree. A single click in Explorer
opens a replaceable preview tab with an italic title. Double-clicking, pressing
Enter, editing, renaming, or dragging its tab keeps it open. New files and direct
file links open permanent tabs. A failed file read preserves the current tab.
Switching worktrees restores their files and draft editors. Closing the last content tab leaves an
empty view. Closing a dirty editor asks before discarding it. Cmd/Ctrl+S saves
only the active file. Drafts are not durable autosaves. Polling reports stale
revisions without replacing dirty drafts. Local storage contains layout and route
preferences, never draft file contents or private conversation text.

Monaco is the default text editor, with a plain-text fallback in File actions.
The compact editor header contains the file path and icon view controls. Clicking
the path copies it; Rename edits the path inline, with Save applying the rename.
Edit/Source, Markdown Preview, and Changes share one view selector. Changes compares
Git HEAD with the current editor text, including unsaved edits, without writing
files. Leaving Changes restores the source editor state. File actions contains
word wrap, editor fallback, copy path, rename, download, and delete. Saves remain
explicit through the Save icon or Cmd/Ctrl+S.
Models are keyed by project, worktree, and stable open-file ID. Cursor, selection,
scroll, and undo history survive tab and layout switches, Markdown preview,
renames, and saves within the project session. Plain-text editors retain their
selection and scroll position. Clean external updates are undoable edits; dirty
drafts retain the stale-revision warning. Closing or replacing a tab releases its
model; leaving the project releases all models. Reloading starts a new session.

Explorer's more-actions menu toggles dotfiles and Git-ignored files, both hidden
by default. Dotfile filtering includes dot-prefixed directories. The API reports
ignored saved paths using the linked checkout's Git ignore rules and HEAD index;
tracked files remain visible even when an ignore pattern matches. These filters
only affect Explorer visibility, not saved snapshots or Source control.

Explorer remembers its filter, collapsed folders, scroll, and visibility options
per worktree for the session. Selecting a file reveals its ancestors without
moving keyboard focus. Manual folder collapse remains until the selected file
changes. Hidden active files offer an explicit Reveal active file action that
clears the filename filter and enables the required visibility options. Saved Git
changes use A/M file badges and aggregate A/M/D folder badges; deleted files do not
create Explorer rows. These markers are separate from unsaved tab indicators.

Removing a worktree preserves its branch, history, metadata, and conversations.
Dirty removal requires confirmation; Main cannot be removed. Restore recreates a
removed checkout at its branch head. Restoring an unexpectedly missing active
checkout recovers its last saved snapshot, including uncommitted changes.
Queued or active agent runs block human writes and removal, including on Main.

## HTTP and compatibility

`/api/v1/projects/{id}/worktrees` provides list, create, and get operations.
Worktree-scoped routes provide file reads, diff, save, commit, discard, remove,
and restore. State includes `head_commit`, independent saved `revision`, lifecycle,
files, changed files, and current writability. File mutations require the expected
saved revision and an idempotency key. Stale writes fail without overwriting files.

Conversation requests accept `worktree_id`; `task_id` remains a compatibility
alias, and conflicting values are rejected. The physical `project_tasks` table
and legacy metadata routes remain compatible. Existing task IDs and session
branches are preserved. New conversations without an explicit binding use Main
once the project has been materialized. Legacy history reads remain available;
the auto-commit `/repository/changes` endpoint rejects migrated repositories with
`repository_upgrade_required_use_worktrees`.

## Persistence and recovery

A saved revision is an internal Git snapshot under
`refs/polycolab/worktrees/<worktree UUID>`, separate from branch history. It records
the saved file tree and its human branch head. SQL prepares the idempotency receipt
before applying a change. After a final authorization check, a fsynced journal
records the accepted operation. Recovery under the repository lock finishes its
ref updates and reconstructs the complete checkout before reads or writes resume.
Files and directories are fsynced before acknowledgement. SQL receipt completion
can be recovered from the snapshot ref if the process stops after Git succeeds.
A prepared SQL receipt alone never authorizes replay of an unapplied write.

The API uses a single-host repository lock plus optimistic revision checks.
Canonical directories are service-owned. User code never executes there, and
shared Git metadata is never mounted into an agent sandbox. External Git imports,
branch switching in place, detached checkouts, terminals, and persistent dependency
environments are outside this implementation.

## Hosted runs

Private runtime protocol 4 pins the worktree ID, human HEAD, and saved revision.
Runs on the same worktree serialize across private conversations. A disposable
sandbox receives a bounded bundle, checks out the pinned branch head, and restores
the saved overlay as uncommitted files. The controller has no SQL credentials and
the guest has no service or provider credentials.

On successful execution, a guest transport checkpoint captures the resulting
file tree. The service validates the bundle in an isolated repository and imports
that tree into the canonical saved state. Guest commits do not advance the human
branch. Completion requires the service's save acknowledgement. Failed or cancelled
runs guarantee only the last acknowledged state; unsent sandbox changes are not
guaranteed. Lease generation, cancellation, deadline, membership, and pinned
revision checks fence imports. Public-destination runs cannot carry private files.
Older controllers cannot claim protocol 4 work.

## Limits

The default quota is 64 MiB per project, configurable from 1 MiB to 1 GiB. It counts
repository objects, checkout files, and recovery metadata. Retained history and
snapshots count even after files are deleted. Trees contain at most 4,096 regular
files and 16 MiB of content. Git output and bundle transfers are bounded at 16 MiB;
imports may introduce at most 256 guest commits. Browser uploads are limited to
700 KB to fit base64 within the core request limit.

Paths reject traversal, `.git` components, control characters, symlinks, submodules,
and non-regular files. Git runs without hooks, global/user configuration, arbitrary
protocols, or a shell. Process, output, and file-size limits remain enforced.
Generated build output and large datasets belong in artifact storage. Guest
`.gitignore` rules control which new files are included in transport checkpoints.

## Migration, backup, and rollout

SQL revisions are `20261011_native_worktrees` (PostgreSQL) and
`local_20261011_native_worktrees` (SQLite). They add rollout and run-binding fields;
they perform no filesystem operations. With admissions and API writes stopped,
drain runs, then back up SQL and the **complete repository directory** together,
including bare repositories, linked checkouts, and recovery journals.

Materialize each existing project using a project writer's user ID:

```sh
uv run --directory src/backend python -m polycolab.operations.materialize_worktrees \
  --project PROJECT_UUID --user WRITER_UUID
```

The command is resumable, retains existing IDs and branches, gives discovered
branches generic member-visible names, leaves archived records removed, and
verifies active checkouts. Existing private conversation titles are never copied
into worktree names. A fresh empty repository provisions Main on first worktree
access; populated legacy repositories require the materialization command.
Deploy the new API, browser, controller, and guest image together. Verify Git
inventory, saved snapshots, and a save/commit cycle before reopening writes.

Restore SQL and repository storage from the same stopped-write backup. Do not
recreate a missing registered repository as an empty one, prune internal refs,
or run immediate object garbage collection: prepared receipts may still refer to
unreachable objects. Rollback requires restoring the coordinated backup or
keeping the new storage disabled; downgrading the schema is unsupported.
