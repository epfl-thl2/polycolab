# Saved conversations

Application snapshots live in `entities/conversation.py`.
Each saved conversation has one stable UUID.
`Conversation` holds ownership, optional project scope, lifecycle, sharing, pinned
configuration, working context, and hierarchy. Transcript pages are separate values.
Execution and usage summaries remain explicitly absent when not loaded.

## Persistence

`conversations` and `conversation_items` store canonical metadata and typed transcript
entries. `conversation_configurations` stores the immutable pinned agent identity,
harness identity/version, optional connection protocol, and private prompt override.
Runs, event streams, usage, grants, leases, and private runtime bindings remain separate.
Private runtime references are never fields on conversation snapshots.

Converters explicitly reconstruct typed immutable values and normalize UTC timestamps.
Store methods return materialized snapshots, allocate sequences atomically, and never
commit their caller's transaction. They validate parent/root/project consistency and
spawning references. Parentage and configuration have no update operation.
Configuration is additionally immutable in migrated PostgreSQL and SQLite databases.
There is no public child-creation operation.

Transcript items distinguish human, agent, tool, and system authorship; message,
tool-call, tool-result, and safe-error payloads; completion/interruption state; and
user-visible versus model-only content. Unknown historical call IDs, arguments,
outputs, observed models, and token counts remain unknown. Reservations are distinct
from observed usage. Agent items retain pinned agent-version attribution.

Execution events and their semantic items commit atomically. Deterministic item IDs
prevent replay from duplicating tool/error entries. Prompt construction selects only
visible messages within the run's pinned input boundary; storing tool/error entries
does not make them additional model input.

## Historical cutover

The conversation and workspace-only migration branches join at a merge revision; either
previous branch head can upgrade without stamping or rewriting its history.
Paired forward migrations rename agent tables in place, preserving their IDs and
dependent foreign keys. A causal merge preserves message order and each run's event
order, using timestamps and source IDs only for unconstrained ties. It translates
run input boundaries to the new item sequences. Committed event IDs, cursors, and
payloads remain unchanged. Backfill runs online; offline SQL is for schema inspection.

Direct-provider histories become private `legacy_direct` conversations. Their saved
request and response text becomes transcript items, and their original turn UUIDs
become immutable `legacy_conversation_executions` identities. Request IDs, selected
provider connections/models, recorded failures, token observations, and reservations are retained.
Pending requests become interrupted with a stable failure code. Copy verification
precedes removal of the superseded direct-chat tables.

Direct inference routes and wiring are retired; `/api/v1/chat/conversations` has no
compatibility API. Shared model-gateway infrastructure remains available to agents.
Legacy history permits owner reads and title/archive changes, but no new execution,
resumption, sharing expansion, or conversion into an agent conversation.

## Conversation API and participation

`/api/v1/conversations` is the single human conversation API. Creating a conversation requires a
project and current editor or owner membership. Agent version, harness and
prompt configuration are fixed at creation. The server admits supported execution
capabilities; storing an arbitrary harness identifier does not enable it.

| Operation                                           | Endpoint                                                 |
| --------------------------------------------------- | -------------------------------------------------------- |
| Create or list accessible conversations             | `POST/GET /api/v1/conversations`                         |
| Read metadata; owner changes title or archive state | `GET/PATCH /api/v1/conversations/{id}`                   |
| Paginated typed transcript                          | `GET /api/v1/conversations/{id}/items`                   |
| Authorized immediate children                       | `GET /api/v1/conversations/{id}/child_conversations`     |
| Submit a human message or interrupt one named run   | `POST /api/v1/conversations/{id}/events`                 |
| Committed updates and reconnect                     | `GET /api/v1/conversations/{id}/stream`                  |
| Read sharing; owner changes sharing                 | `GET/PATCH /api/v1/conversations/{id}/sharing`           |
| Paginated run history                               | `GET /api/v1/conversations/{id}/runs`                    |
| Inspect a run or explicitly queue a successor       | `GET /api/v1/runs/{id}`, `POST /api/v1/runs/{id}/resume` |

Conversation listings filter by project, archive state and origin. Transcript pages use
an opaque sequence cursor in `next_cursor`; conversation, child and run listings return
`X-Next-Cursor` when another page exists. Metadata does not embed transcript pages.
The former agent-conversation and agent-run APIs have no compatibility routes.
Run inspection and resumption use human authentication. External agent API keys retain
their separate delegated project-file APIs.

Private conversations remain owner-only even when another user owns the project.
Members can view sharing permits current members to read. Members can participate sharing additionally permits editors and owners to submit messages. Child
sharing is independent; neither hierarchy links nor child listings reveal
inaccessible descendants.

Message acceptance commits a human item and queued execution together, then returns
202 with their stable identities. Exact retries return the original admission
receipt, including after archival; changed content or authority conflicts. The
receipt describes acceptance; run reads supply current execution state. A retry
still requires current read access and the original sender. New admissions use the
sender's provider connection, quota and delegated authority. Human events cannot append
worker output or impersonate transcript authors.

The sender can interrupt their own runs; the conversation owner can interrupt any run.
Interrupting a terminal run does not affect its successor. Resuming private context
and authority is restricted to the original sender. Claims, model dispatch, tools,
workspace operations, transcript output and completion recheck current membership
and sharing. Revoked workers may reconcile observed usage and report termination.
Context manifests are worker-only; private output artifacts remain restricted to the run sender;
transcript access does not grant those inputs and outputs.

SSE reconnects use `Last-Event-ID: run_sequence:event_cursor` and replay committed
events. An unfinished earlier run holds back later-run events so a later cancellation
cannot advance the cursor past earlier output. Completion events reference the saved
assistant item; they do not duplicate its Markdown. Authorization is rechecked while
streaming. Responses omit model-only items, private runtime references and tool
arguments/results. Share previews use the same visible transcript projection. Only
the owner receives the private system-prompt override.

The browser retains project conversation URLs, renders typed items and attributable
participants, exposes sharing and per-run interruption controls, and clears its
transcript after access revocation. Retired direct histories are available under
**Settings → Saved chat history**, including standalone conversations. They offer
reads, rename and archive/restore without execution controls.

## Maintenance cutover

Stop new admissions, drain or explicitly terminate active work, then stop all
writers. Back up the database and its matching artifacts. Apply the online migration,
deploy matching backend/browser/workers, smoke-test history and execution, then reopen
admissions. Rollback restores the matching backup and application version; there is
no mixed-version compatibility window. See the [rollout gates](../roadmap.md#unified-conversations).

## Verification

Deterministic tests cover SQLite schema parity, populated mixed-history migration,
causal ordering, exact text and execution accounting, preserved runtime references,
store materialization and rollback, hierarchy consistency, and conversation access policy.
PostgreSQL equivalents require `M0_POSTGRES_TEST_URL`. Compilation of offline SQL does
not establish migration acceptance against a populated PostgreSQL database.
Native/provider and target-deployment acceptance remain separate release gates.
