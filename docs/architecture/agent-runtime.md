# Agent runtime

The [microsandbox/Codex controller candidate](hosted-controller.md) implements concurrent allocation and private artifacts.
Deployment awaits native acceptance.
The legacy worker described below remains the deployed path.
Its duplicate database-backed harness no longer exists.

The built-in runtime executes the platform-controlled Researcher and Critic as a private Python worker.
Agent versions are immutable and sessions pin an exact version.
The worker has no browser-facing endpoint, arbitrary uploaded code, terminal, filesystem, or user-defined callable surface.

PostgreSQL owns every product-visible session, message, run, normalized event, usage observation, and historical runtime binding, but only the Application API accesses it.
A worker may lose all local state and be replaced without losing the transcript or browser cursor.
Runtime and provider identifiers remain private binding data and are never serialized by public API schemas.

## Lifecycle

- Sessions are private to their initiating user.
  Project membership alone does not grant session access.
  Archived projects accept no new sessions or turns.
- Each turn snapshots the requesting user's provider-profile credential version and model ID without storing a provider key or raw grant on the run.
- Follow-ups are ordered queued runs.
  Only the earliest nonterminal turn in a session may execute.
- Resume creates a queued successor linked to a terminal run.
  Terminal rows are never reopened.
- Claims use finite leases and generations.
  Stale generations cannot append events or complete reclaimed work.
- The API commits events with a per-run cursor and idempotency key before browser SSE can observe them.
  An exact retry returns the original cursor.
  The API rejects reuse of the key for different content.
  Reconnect reads strictly after the last committed ID.

## Model and tool boundaries

Workers authenticate to a private Runtime API.
They use that API to:

- Claim an immutable execution envelope.
- Renew leases.
- Request one-use model grants.
- Commit events, usage, and terminal state.
  The worker has no database credential and does not call Application API persistence services directly.

Workers call private logical gateway modules inside the Application API.
They exchange a short-lived one-use grant with the Model Gateway and receive only normalized deltas, terminal reasons, usage, and stable errors.
They call the hosted-agent Tool Gateway with a separate short-lived run capability.

Runtime requests and claim envelopes have independently configured byte ceilings enforced by both sides of the private connection.
A failed worker or private-API connection leaves the run lease to expire.
The API revokes the old capabilities, increments the generation, and rejects all stale writes before a replacement worker resumes the run.

The runtime bounds provider streams by time, bytes, events, output, cost, and retries.
Ambiguous I/O, incomplete streams, and provider 5xx responses are not blindly replayed.
Browser SSE reads committed Polycolab events rather than relaying a provider connection.

Live database contention, private-network policy, real-provider streaming, and worker deployment credentials require **Deployment verification** even when deterministic local tests pass.
