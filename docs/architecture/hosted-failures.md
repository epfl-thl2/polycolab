# Hosted execution failure acceptance

The recovery policy is conservative:

- Retry only before possible external effects.
- Require explicit resume after an ambiguous dispatch or mutation.
- Quarantine an uncertain slot while other chats continue.
  No finite test suite proves every possible failure mode.
  Native containment and deployment evidence remain required.

| Failure boundary                                       | Implemented response                                                                                                       | Repository evidence                                    |
| ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Missing/expired readiness or stale controller          | Reject new claims. Retain history. Recheck the incarnation and slot inside the allocation transaction.                     | `test_hosted_artifacts.py`, `test_hosted_scheduler.py` |
| Concurrent claims / noisy tenant                       | Serialized physical allocation, global and tenant limits, per-session order                                                | Real PostgreSQL `test_hosted_scheduler.py`             |
| Queue deadline / dead worker / API restart             | Run independent, bounded recovery batches. Apply terminal expiry or a conservative retry before possible external effects. | `test_hosted_recovery.py`                              |
| Duplicate finish / lost finish response                | Retain an immutable payload receipt for each generation. Reject changed retries.                                           | `test_hosted_recovery.py`                              |
| Provider error, timeout, malformed or oversized output | Isolate the run. Bound transport. Settle conservative usage. Do not redispatch automatically.                              | `test_codex_runtime.py`, `test_hosted_recovery.py`     |
| Provider terminal incomplete response                  | Validate and settle reported usage. Do not deliver an incomplete answer                                                    | `test_hosted_recovery.py`                              |
| Cancellation / expired lease / changed credentials     | Recheck authority before dispatch, delivery and exports. Stop local work when lease budget expires                         | `test_codex_runtime.py`, `test_hosted_artifacts.py`    |
| Lost process / failed stop / failed scratch deletion   | Durable journal, quarantine and retained physical occupancy. Reconcile before reuse                                        | `test_hosted_recovery.py`, `test_hosted_scheduler.py`  |
| Unsafe or late file export                             | Bounded selected paths, storage verification and atomic completion binding                                                 | `test_hosted_artifacts.py`, `test_codex_runtime.py`    |
| Browser reconnect / disabled admission                 | Poll canonical history. Retain downloads from old completed runs. Show an explicit resume warning.                         | `svelte-project.spec.ts` hosted-history case           |

Run repository regressions:

```sh
pnpm run api:check
pnpm run api:contract:check
pnpm run typecheck
pnpm run test
# Uses disposable schemas; never migrate a development database directly.
M0_POSTGRES_TEST_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/DATABASE \
  uv run --directory src/backend pytest ../../tests/backend/test_hosted_scheduler.py -q
pnpm --filter @polycolab/web exec playwright test \
  --config ../../tests/web/browser/playwright.config.ts --grep 'hosted run history'
```

## Native gates still required

Deployment requires an accepted Linux host and curated image.
The following command is an opt-in harness for a **disposable, idle execution account** with at least two prepared slots and the accepted image policy.
Stop its controller first.
It starts real VMs, cancels one, checks that the other can still initialize Codex, and verifies scratch deletion.
It uses no provider or application credential.

```sh
POLYCOLAB_NATIVE_CONTROLLER_CONFIG=/etc/polycolab-execution/controller.toml \
  uv run --directory src/backend pytest ../../tests/execution/test_hosted_native.py -q
```

A skipped test is not native evidence.
Before enabling hosted agents, also record:

1. CPU/memory/PID/disk exhaustion and the independent systemd deadline.
   No descendant process, open guest mount or writable scratch remains before reuse.
2. Controller SIGKILL, host reboot, disconnected API/database, corrupt/full journal storage, ambiguous VM creation and failed stop.
   Verify quarantine and recovery while healthy chats progress.
3. Offline networking, read-only inputs, host credential isolation, pinned image identity and cold/warm image behavior on the selected host.
4. Five real chats across multiple users/projects, with capacity four.
   Verify at most four active attempts and a queued fifth attempt.
   Cancel one attempt.
   Simulate the loss of another attempt.
   Check that other work continues without duplicate provider dispatch or contribution.
5. Actual Responses provider, key revocation/rotation, object storage interruption, upload/GC races, browser reconnect, old-file download and cross-user denials.
6. Upgrade/drain/rollback with protocol mismatch and a full API/database outage.
   Retain completion receipts, immutable history and quarantine records.

Capture versions, image digest, host resources, scenario, expected invariant and observed result.
Record content-free identifiers and timing only.
Do not remove the legacy worker or claim production readiness until these deployment gates pass.

## Shared controller hardening

Read tools omit write-provenance headers; write tools retain their source cursor.
Invalid guest Unicode and malformed claims become bounded protocol errors.
Input preparation, output collection, journal acknowledgement and scratch removal
run off the async loop. Cancellation joins filesystem work before cleanup.
Startup retries transient readiness and termination-report failures; journal
acknowledgement failures retain the record for an idempotent retry.
Reconciliation includes retired slots after a capacity reduction. Claim responses
are checked against the request interval, and elapsed transport time reduces the
remaining lease budget.

`test_executor_backends.py` covers backend identity, read/write provenance,
malformed frames and claims, delayed responses, cancellation-safe filesystem work,
retired slots, launch policy and quarantine. These regressions complement the
native tests; they do not prove all host failure modes.

The Docker/gVisor native suite is separate from the microsandbox VM suite:

```sh
POLYCOLAB_GVISOR_TEST_CONFIG=/etc/polycolab-execution/controller.toml \
  uv run --directory src/backend pytest ../../tests/execution/test_gvisor_native.py -v
```

Use an idle disposable host with two finite slots. The suite checks real Codex
startup, offline networking, read-only inputs, output transfer, cleanup, independent
deadlines with intact, truncated and removed journals, controller SIGKILL/reconciliation
and cancellation without stopping the other slot. Journal restoration in these
synthetic tests occurs only after observing termination; production recovery still
requires valid journal records. Resource exhaustion,
daemon outage, reboot and live-provider acceptance remain
separate deployment gates.
