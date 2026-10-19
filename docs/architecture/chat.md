# Direct provider chat

The `chat` capability serves authenticated humans at `/api/v1/chat`.
Standalone conversations have no project ID; project conversations require current membership.
Only the creator can list or read a conversation, including in public projects.
Sending requires an active contributor or owner role for a project conversation.
Agent credentials cannot call these human routes.

`chat_conversations` stores ownership, optional project scope, title, ordering, and a finite active request lease.
`chat_turns` stores each user's text, the selected profile and model, reply or stable failure, and token observations.
The PostgreSQL and SQLite Alembic revisions share frozen DDL.
No chat row creates a research revision, execution run, tool capability, or worktree binding.

Admission atomically claims the conversation and commits the user turn before provider I/O.
Database transactions do not remain open during credential decryption or provider inference.
One conversation permits one in-flight request.
A client request UUID identifies an exact message/profile pair.
Repeating it returns the saved pending or terminal turn; changed input with the same UUID conflicts.
Ambiguous provider requests are not replayed automatically.
After an interrupted process, an expired lease becomes a durable failed turn on history refresh or the next admission.
A stale completion cannot overwrite a recovered turn or release a successor's lease.

The model gateway reads only the requesting user's encrypted credential.
It honors the profile's `wire_api`: Responses or Chat Completions.
Both protocols send the complete successful conversation history and current user message, with no tools.
Responses uses `store: false`.
Provider-generated tool calls, truncated responses, missing usage, and empty output fail safely.
Provider failures expose stable codes rather than raw response bodies or credentials.
The configured pinned transport retains DNS/egress checks and finite I/O bounds.
Direct chat additionally bounds total stream duration, chunks, bytes, output tokens, and estimated request cost.

Chat consumes configured per-user and per-project request windows.
Daily chat admission uses the execution settings' token and cost ceilings, counted against conservative chat reservations.
Reservations remain charged for failed or ambiguous requests.
These daily chat counters are separate from hosted execution usage.

Direct provider chat has no browser page or navigation entry.
The browser's existing project conversations use agent sessions, with their own worktree context and execution requirements.
`ChatComposer.svelte` remains shared UI infrastructure for those sessions.
The direct chat API includes only explicit conversation text, without automatically attaching research or files.

Deterministic API tests exercise both protocols, saved follow-ups, retry identity, failures, ownership, and recovery against SQLite.
Mocked browser journeys check that retired Chat entry points do not load direct-chat conversations and that the existing project workflow remains accessible.
These checks do not establish live-provider conformance, PostgreSQL contention, or target-deployment acceptance.
