# Hosted controller

The repository implements a Linux hosted-agent controller using microsandbox 0.6.18 and Codex CLI 0.154.0.
**Native acceptance and deployment are outstanding:** deployment requires an accepted Linux host, curated image, and real VM/Codex/provider/browser journey.
See the [deployment procedure](../../deploy/execution/README.md).

## Implemented

`execution/service.py` runs a bounded concurrent pool (default four attempts).
`execution/linux.py` launches a separate transient systemd user service per attempt.
Each requires a private finite filesystem for all mutable SDK state, image cache, guest disk, inputs, outputs and logs.
Systemd independently limits wall time, CPU share, memory and process count.
`execution/executor.py` refuses bare execution without actual Linux cgroup containment.
Inside that boundary, `execution/microsandbox.py` creates a fresh digest-pinned, non-root, offline VM.

Guest CPU/process limits supplement host containment.
There is no host-process fallback for guest work.

The controller journals each unit before launch.
Startup holds an exclusive state lock, stops journaled attempts and reports exact generation termination before claiming.
The controller quarantines a slot with unconfirmed cleanup while healthy slots continue.
Its physical reservation remains occupied until the controller confirms cleanup, even beyond the usual release bound.
Other reservations survive logical lease loss until confirmed termination or the independent deadline plus 30 seconds.
Protocol version 2, controller incarnation and physical slot binding fence new claims.

Readiness cannot replace an unexpired controller incarnation.

`execution/allocator.py` connects the existing scheduling tables to hosted admission and claims.
Frozen runtime specifications produce immutable work costs.
User/project virtual runtimes order eligible work.
Claims serialize capacity allocation and enforce global, per-user and per-project limits, while preserving earlier-turn ordering within a session.
Real PostgreSQL contention tests cover concurrent claims and physical slot retention.

`agents/runtime/controller.py` supervises the bounded Codex app-server protocol.
The guest bridge sends Responses requests through process I/O to the private API.
Provider credentials stay in the API and service credentials stay in the host controller.
Inputs are exact authorized artifact pins, downloaded and hash-checked before mounting read-only at `/inputs/<artifact UUID>` (16 MiB aggregate limit).
Research tools retain current API authorization and generation fencing.

`model_gateway/hosted.py` reserves each provider dispatch durably before outbound I/O.
A request key cannot dispatch twice.
Completion settles observed usage.
An ambiguous or interrupted dispatch retains its conservative reservation.
Claim processing and the independent application reconciler both recover expired pending dispatches.
Valid terminal incomplete responses settle observed usage without delivering an incomplete answer.

Settlement survives lease loss and uses frozen limits/rates.
Database and credential operations run off the async request loop, with bounded PostgreSQL lock/statement waits.
The async IP-pinned transport has bounded I/O and no redirects or automatic retries.
The gateway buffers responses until it validates terminal usage.
This is not live provider-token streaming.

The guest can register an `export_artifact` declaration for a file in `/outputs`.
After stopping the VM, the controller reads only those paths with descriptor-based link/path/type/count/byte checks, then uploads verified bytes through the API.
Downloads require a completed run and its owner, including the shared artifact endpoint.
These artifacts cannot be attached directly to research.
Session output is not publication, proof certification or a retained whole project.
Commands, raw stdout and reasoning notifications are not copied into chat history.

The API advertises session/hosted availability and the browser displays Sessions and explicit file downloads.
Compatible executors renew readiness every ten seconds.
Advertisements expire after 45 seconds.
New hosted admissions require a live matching executor.
Existing chat, history, follow-ups, cancellation and reconnect APIs remain in place.
Standalone verification stays disabled in this hosted-first service and UI.

The application-owned `execution-reconciler` Compose service runs bounded recovery batches every five seconds, even with no live executor or new claims.
Expired hosted runs with any possible provider/tool/contribution effect fail with an explicit-resume code.
Only attempts known to precede external effects can requeue, within their original deadline and attempt budget.
Deadline and cancellation transitions revoke capabilities.
Completion receipts make identical finalization retries safe and reject changed payloads.
Durable aggregate recovery/settlement counters contain no run, user or provider identifiers.

Per-attempt provider failures do not cancel the pool.
Heartbeats use a monotonic lease budget.
Control-plane retries have finite limits and apply only to idempotent operations.
Attempt journals are atomically replaced and fsynced.
Cleanup deletes work directories, including undeclared files, before returning a slot.
A failed journal write during failed cleanup cannot acknowledge successful termination.

Sessions polls canonical run history, offers explicit resume for failed/timed-out runs, and lets users select files from older completed runs.
Readiness disables new execution without hiding history.
The generated client includes the bounded `GET /api/v1/agent-sessions/{session_id}/runs` listing and `execution_available`.
Customized Hosted Codex sessions persist a selected harness and additional system prompt on the session.
Every run in that session includes the prompt after the pinned platform agent instructions.
The selected gateway profile still supplies the model endpoint and remains a per-turn credential boundary.

New provider profiles default to Responses.
The migration preserves historical profiles as chat-completions.
`RUNTIME_CODEX_IMAGE` pins the immutable runtime specification for new/resumed runs.
Legacy workers cannot claim these runs.
External agents continue using their existing credentials and shared research APIs.

## Removal and remaining acceptance

The duplicate database-backed built-in loop, its unused adapter contracts and the SBX stub were removed.
The old private-API worker and Compose service remain until native acceptance passes.
They are not a fallback for hosted Codex runs.
Remove that compatibility implementation only after the real deployment succeeds.

`execution/preflight.py` checks the Linux prerequisites and loads/verifies a curated image archive in every slot.
It does not prove containment.
The deployment procedure specifies native resource-exhaustion, offline-network, credential, crash/restart, cancellation, stale-result, provider and browser acceptance.
Those results are still required before production enablement.
Standalone Python/Lean runner images and verification assurance are separate future work.

Local protocol tests use synthetic Codex frames.
Artifact tests use in-memory object storage.
PostgreSQL tests use disposable schemas on the local service.
None of these constitutes native sandbox or deployed end-to-end evidence.

## Verification

The [execution test guide](../../tests/execution/README.md) describes local and native checks.
Local mocked tests do not establish Linux containment, provider acceptance, or deployment readiness.
Resolve the [known failure cases](hosted-failures.md) before production enablement.
Complete the native gates before production enablement.
