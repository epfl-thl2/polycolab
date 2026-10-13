# Linear projects

Projects select `git` or `linear` at creation. The browser offers Linear history by
default; omitted API fields retain the Git default.
Existing projects keep their mode. Library copies into a new project also accept a
mode. Project research versions and publication authority are unchanged.

## Durable collaboration

FastAPI remains the authority for membership, roles, project state, quotas, and
accepted changes. PostgreSQL stores stable file identities, Yjs documents, current
bytes, ordered operations, checkpoints, private AI batches, and run snapshot
bindings. SQLite uses the same contracts in local mode. An internal Node service
validates and prepares Yjs updates against supplied committed state. It has neither
database credentials nor access to the project volume. Its ephemeral presence
registry expires disconnected members after 15 seconds.

Each text file has one Yjs `content` text and a stable UUID. Renames retain identity;
deletions leave tombstones. Files are opened lazily. Monaco uses Yjs binding and
per-file local undo; the plain text fallback also generates incremental edits.
Binary files use whole-file replacement. Paths, modes, file count, transfer size,
and project storage are checked by the API. Filesystem symlinks and Git internals
are not accepted as project files.

The WebSocket authenticates its first frame, checks the browser origin, and
rechecks current authority throughout its lifetime. Tokens never appear in URLs.
Only committed SQL operations enter the ordered stream. A save acknowledgement
means the operation, current bytes, and retry receipt have committed together.
Reconnect replays from the last stream sequence; repeated request keys cannot
apply twice or change their payload. File operations and AI results use optimistic
sequence checks. Yjs text updates can incorporate concurrent changes within an
epoch. Permission failure or restore preserves pending text for explicit recovery.

Editing pauses when disconnected. Pending text survives in the open tab, with no
browser database or localStorage copy. Closing a tab with unsaved changes prompts
the user. This is not a durable offline editor.

## History and the project volume

Linear projects use the existing repository volume. Private Git refs store exact
checkpoint trees and a single-parent checkpoint history; users do not manage Git
branches in this mode. Immutable materialized directories live at
`<project UUID>.linear/<epoch>-<sequence>`. A checkpoint writes and fsyncs a staged
directory before making it visible. Agents receive bounded bundles of exact
checkpoint contents in their isolated execution directory.

Accepted operations are the detailed history. Periodic checkpoints are created
on edits at most once per minute; users can name checkpoints. Checkpoints also
capture agent input, refresh input, and the state before applying AI changes or
restoring. Checkpoint failure does not retract an accepted edit. A later edit or
explicit checkpoint retries materialization. Current documents, checkpoint JSON,
operation payloads, retained AI batches, Git data, and materialized directories
consume the project quota. History is retained; storage limits stop further writes.

Only owners restore the entire project. Restore appends a new operation, starts a
new epoch, and creates fresh document IDs. Old clients and old agent snapshots
cannot silently overwrite the restored project. The pre-restore checkpoint keeps
the former contents available. There is no history rewrite.

## Agent execution

API and execution controllers must be upgraded together to protocol 6, with a rebuilt
curated guest image. Protocol-4 controllers are rejected for both project modes.
Private runtime protocol 6 pins an exact checkpoint for each turn. The normal
execution allocator and existing per-user/project limits still apply; linear
projects introduce no extra one- or two-chat cap and do not serialize unrelated
conversations on an archived Git worktree.

`workspace_status` reports shared changes since the input snapshot.
`workspace_refresh` is explicit: the controller requires no active local tool, and
the guest checks for remaining processes. The API merges the local contribution
with a newer shared checkpoint. It persists a prepared generation; the guest
installs it and the controller acknowledges installation before the binding can
advance. Unacknowledged refresh prevents completion export. Conflict leaves the
agent's existing files intact. Refresh changes the agent directory, never the
shared project. The agent must reread affected files and repeat relevant checks.

On completion, the API validates a bounded Git bundle and computes a stable-ID
contribution, including renames. Independent text changes merge against the
latest shared files. The result applies as one operation after rechecking lease,
cancellation, deadline, membership, epoch, and sequence. Creates, replacements,
renames, deletions, and executable modes succeed together. Shared edits remain
available while the agent reasons and executes.

Conflicts preserve the whole result in a creator-private pending batch. No paid
retry is automatic. The creator can retry the merge, review original/current/
proposed contents and apply a manual resolution, or open a reconciliation draft
in the originating chat. Sending that draft explicitly starts a new turn on the
latest snapshot. Revert computes the inverse of an applied batch against current
files and preserves conflicts for review. A public research run cannot use private
linear files.

## Conversations and conversion

Chats are private initially. The creator can preview the complete user-visible
transcript and share it, including future messages, with project members. Shared
viewers can read messages and live responses; only the creator sends messages,
changes visibility, or controls runs. System prompts, raw tool events, private AI
batches, and session artifact downloads are excluded from the shared view.
Unsharing revokes further access but cannot recall content already viewed.

Owners can preview and convert a selected Git worktree's saved revision, including
saved uncommitted changes. Existing runs must drain. A durable conversion receipt
fences Git writes and new run admission during preparation. The initial linear
checkpoint is durable before the mode switches. Retrying the same conversion is
safe. Original branches, saved worktrees, and historic run bindings remain in the
read-only Git archive. Existing chats can continue with their history and an
explicit notice that new turns use the linear project.

## Operation and verification

Set `PROJECT_REPOSITORY_DIRECTORY`,
`COLLABORATION_URL`, and the same private `COLLABORATION_TOKEN` (at least 32
characters) in the API and Node service. Keep the Node service on the internal
network; expose only the API WebSocket. The local runner starts the sidecar;
Compose builds its separate image. Production uses an immutable
`POLYCOLAB_COLLABORATION_IMAGE` and an explicit token. Back up SQL and the complete
repository volume together. Restore both before reopening writes. Presence needs
no backup. The project mode selects linear or Git behavior; no rollout flag is required.

`tests/backend/test_linear_workspace.py` and `test_linear_agents.py` use actual
Yjs and Git transport with SQLite and disposable PostgreSQL schemas (set
`M0_POSTGRES_TEST_URL`). `tests/web/browser/local/linear.spec.ts` exercises two
real browser members through the disposable local-mode runner. Native VM agent
execution and target deployment acceptance are separate release gates; API bundle
transport tests do not establish those gates.
