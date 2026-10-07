# Workspace files

Implemented: member file API, browser editor, history, stale-save protection,
merge review, durable Git/SQL receipts, hosted bundle transport and guest checkout
helpers. Native Linux microsandbox acceptance remains a deployment gate.

## Storage and ownership

Each workspace has one bare Git repository, `<workspace UUID>.git`, under the
API-owned `WORKSPACE_REPOSITORY_DIRECTORY`. The setting is optional; without it
file endpoints report disabled. Docker Compose mounts a persistent named volume;
Docker-free development selects `.local/repositories`. The API image includes
Git (2.38 or newer is required for merge-tree). No Git HTTP/SSH endpoint is exposed. The initial deployment requires a single
API host and a local POSIX filesystem with working `flock` and atomic ref updates.
API processes on that host share the same repository directory and locks.

SQL retains accounts, memberships, research records, sessions, runs, repository
registration, mutation receipts, and input/output commit IDs. Git owns working
file content and history. Garage retains artifact bytes. No existing research
record is migrated, mirrored, published, or automatically updated by a file save.
Tasks are durable workspace metadata with a title, creator, archive state, and one
saved working-copy branch. Creating a task forks the current shared head into
`tasks/<task UUID>` immediately and does not require agent execution. The API
requires file storage and uses `client_request_id` as the retry identity. Task
metadata is member-visible; its nested chats remain creator-private. Task list,
get, create, and update routes live at `/api/v1/workspaces/{id}/tasks`.
Archiving rejects queued or active task runs and preserves the saved branch.
Archived task branches remain readable and reject new writes or conversations.

Repository content is always members-only, including in public workspaces.
Read-only members can inspect saved files and branches. Contributors and owners
can save; workspace archive and membership checks are enforced on the server.
Chat ownership and privacy are unchanged. Git author strings from guests are
untrusted display metadata; authenticated SQL receipts record the saving actor.

## Collaboration

Humans edit shared `main` or a named task copy in the workspace’s tabbed editor,
then **Save**.
Member workspaces use four areas: a thin page-navigation rail at the far left,
tasks with nested private conversations on the left, unified content tabs in the middle, and
switchable Explorer, Source control, and Details tools on the right. The workspace
root opens New chat when writing and agent execution are available, otherwise
Overview. Explorer provides collapsible folders and filename filtering. Files,
chats, research objects, pages, and diff views share one tab strip; there is no
nested file-workbench frame.

`WorkspaceFiles` remains mounted and keeps independent in-memory drafts while
switching files or workspace sections. Closing a dirty tab or leaving the
workspace asks before discarding work. Cmd/Ctrl+S saves the active file. Markdown
can be previewed beside the editing workflow, and the enhanced source editor
remains available from File actions. Paths create folders on save; Git does not
store empty directories. Saved versions are immutable.
Every save identifies its expected commit and retry key. A stale save returns a
conflict without overwriting newer work; the browser retains the draft, compares
the latest file, and lets its author explicitly choose the new base. Polling every
five seconds refreshes clean editors and reports changes alongside dirty drafts.
Drafts are browser memory, not durable autosaves. Local storage retains layout
preferences and validated route-tab URLs per account/workspace, excluding file
content and file/diff tabs. Source control opens history and merge review as diff
tabs. Task names label saved working copies; branch identity remains secondary.
Selecting a task or opening one of its conversations selects that branch. The
center plus creates a new conversation in the selected task. Shared workspace
contains conversations without a task. Archived tasks have a separate collapsed
section. Other members’ private titles, conversation counts, and run activity are
not included in the panel.
Switching copies asks before discarding any tab drafts. Collapsing the right
panel preserves open editors and their drafts. Narrow screens open the navigator
in the workspace’s right-hand drawer; choosing a file returns to the editor.

A session owner opts into workspace files before queueing a run. Its
`sessions/<session UUID>` branch starts at shared `main`. All workspace members
can inspect saved session branches. While a session has an active run, human
writes to that branch are blocked. Otherwise writers can edit it, update it from
shared files, or review its diff and merge into `main`. Merge checks both expected
heads, uses Git's three-way merge, and requires a complete resolution for every
conflicting file. Binary conflicts offer whole-file choices. Stale previews must
be refreshed. No CRDT, live cursors, automatic agent-to-main merge, or external
repository synchronization is included.

## Hosted workflow

Repository-enabled sessions require the hosted Codex execution capability.
Public-destination research runs cannot carry private workspace files. At claim,
the API pins the task working-copy head and branch in SQL; legacy untasked
sessions continue to pin their own branch. Conversations on one task share that
working copy. Claims serialize task runs across chats, and any claimed, running,
or cancelling sibling blocks another claim regardless of timestamps. Human
writes and task archive use the task lock and reject queued or active runs. A controller with private protocol 3 receives
a bounded bundle and metadata, and the guest makes a fresh clone at `/workspace`.
Codex state lives outside that checkout. The controller holds no SQL credentials
and the guest holds no service or provider credentials.

Agents can run local subprocess workflows and Git worktrees inside the existing
sandbox. Integrate their changes into the primary working-copy branch before finishing;
only that branch is exported. This does not introduce a multi-agent scheduler or
enable Codex native subagent orchestration, which remains disabled by the existing
hosted bridge. On orderly success, the helper commits unignored changes, exports a
bundle, and the API validates and saves the branch before permitting completion.
The next run gets a fresh clone of that saved head. The session UI shows input and
saved output commits. Cancelled, timed-out, or crashed runs guarantee only commits
already acknowledged by the API; a local `git commit` is not a durable service save.

The private import endpoint fences run status, deadline, cancellation, current
membership, worker identity, and lease generation. A branch save is idempotent per
run. Completion is refused until the saved output binding exists. Inputs remain
pinned even if another session or human advances `main`.

## Limits and validation

The default per-repository disk quota is 64 MiB, configurable from 1 MiB to 1 GiB.
History counts toward this limit; deleting a tracked file does not remove its
historical bytes. Bundle transfers and individual Git outputs are capped at
16 MiB. Total run inputs, including artifacts and repository metadata, share the
16 MiB input ceiling. Trees are limited to 4,096 regular files and 16 MiB of content;
an imported branch may add at most 256 commits per run. The browser upload ceiling
is 700 KB to fit base64 JSON within the 1 MiB core request limit.

Reject traversal paths, `.git` components, control characters, symlinks, submodules,
non-regular entries and rewrites of the run's starting history. Imported bundles
are inspected in a temporary bare repository before objects enter canonical
storage. Git runs without hooks, user/global configuration, arbitrary protocols,
or a shell, with process time, output, memory (Linux), and file-size limits.
Repository locks serialize saves and merges; ref updates also compare the old
commit. Large datasets, build trees, and generated outputs belong in artifact
storage. Put temporary files and dependencies in `.gitignore`.

## Recovery, backup, and rollout

Apply PostgreSQL migrations through `20261008_workspace_tasks` or the matching
SQLite migrations. The task migration creates a generic member-visible task for
each existing repository-enabled session, retains its `sessions/<UUID>` branch,
and leaves private conversation titles unchanged. Untasked sessions and shared
`main` are preserved. Existing run bindings snapshot their original branch.
No Git branch rename, content copying, or migration-time Git access occurs. The API prepares and commits a SQL mutation receipt before advancing a
Git ref. It then finalizes the receipt. On subsequent repository access, a pending
receipt whose commit is already reachable is acknowledged; recovery never applies
an uncommitted write on behalf of a revoked user. Retrying the same request and key
returns its saved commit. Prepared receipts may reference unreachable objects;
do not run `git gc --prune=now`, rewrite refs, or remove repository directories as
routine maintenance.

Back up SQL and the complete repository directory as one stopped-write set:

1. Stop new admissions, drain or cancel running agents, and stop every API writer.
2. Take the SQL backup and copy/snapshot the repository volume, including refs,
   objects and configuration. Preserve private filesystem permissions. Back up
   Garage using its existing artifact procedure.
3. Record the schema revision and application/image version with this backup set,
   then resume the service.
4. Restore both SQL and repositories into an isolated deployment. Run
   `git --git-dir=<repository> fsck --full`, verify saved session heads and SQL
   input/output commit IDs, then read history and perform an expected-head save.
   Check pending receipts through the API before reopening normal writes.

An SQL-only backup no longer restores workspace files. Do not pair backups from
different write points or recreate missing registered repositories as empty ones.
For rollback, drain controllers, retain SQL and repository data, and disable file
configuration/UI access. Do not downgrade the new tables. Rebuild the curated
image and controller together for protocol 3; older controllers cannot claim new
hosted work. Existing sessions without repository opt-in keep their prior behavior.

Local automated checks cover save/retry/conflict handling, private access, quotas,
path validation, SQL interruption recovery, clone/checkpoint/restore, linked
worktree integration, hosted lease/cancellation fencing, merge, and browser draft
retention. A real Linux pinned-image checkout/save/restart/cleanup acceptance run
is still required before enabling hosted repository use in production.
