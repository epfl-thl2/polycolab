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
| Browser reconnect / disabled admission                 | Poll canonical history. Retain downloads from old completed runs. Show an explicit resume warning.                         | `svelte-workspace.spec.ts` hosted-history case         |

Run repository regressions:

```sh
pnpm run api:check
pnpm run api:contract:check
pnpm run typecheck
pnpm run test
# Uses disposable schemas; never migrate a development database directly.
M0_POSTGRES_TEST_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/DATABASE \
  uv run --directory backend pytest ../tests/backend/test_hosted_scheduler.py -q
pnpm --filter @polycolab/web exec playwright test \
  --config ../tests/web/browser/playwright.config.ts --grep 'hosted run history'
```

## Native gates still required

Deployment requires an accepted Linux host and curated image.
The following command is an opt-in harness for a **disposable, idle execution account** with at least two prepared slots and the accepted image policy.
Stop its controller first.
It starts real VMs, cancels one, checks that the other can still initialize Codex, and verifies scratch deletion.
It uses no provider or application credential.

```sh
POLYCOLAB_NATIVE_CONTROLLER_CONFIG=/etc/polycolab-execution/controller.toml \
  uv run --directory backend pytest ../tests/execution/test_hosted_native.py -q
```

A skipped test is not native evidence.
Before enabling hosted agents, also record:

1. CPU/memory/PID/disk exhaustion and the independent systemd deadline.
   No descendant process, open guest mount or writable scratch remains before reuse.
2. Controller SIGKILL, host reboot, disconnected API/database, corrupt/full journal storage, ambiguous VM creation and failed stop.
   Verify quarantine and recovery while healthy chats progress.
3. Offline networking, read-only inputs, host credential isolation, pinned image identity and cold/warm image behavior on the selected host.
4. Five real chats across multiple users/workspaces, with capacity four.
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

## Known controller defects queued for the next development iteration

The controller audit identified these unresolved failure cases:

1. Read tools receive a write-provenance header and their rejection can stop the pool.
2. Malformed guest Unicode and malformed claims can escape run-level error handling.
3. Synchronous filesystem operations can block all heartbeats.
4. Transient API failures during startup can leave the service stopped.
5. Journal acknowledgement errors can escape after successful run completion.
6. Reducing capacity can prevent reconciliation of old slot journals.
7. Delayed claim responses can be mistaken for host clock skew.

The automated evidence above does not cover all these failures.
Fix them with regressions before treating hosted delivery as accepted.
Native acceptance is still outstanding.
