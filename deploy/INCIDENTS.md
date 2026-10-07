# Non-execution incidents and safe rollback

These procedures cover service incidents and recovery.
They do not establish completed deployment drills.
Execution and worker-loss acceptance have separate [native gates](../docs/architecture/hosted-failures.md).
Do not start an agent, provider run, or sandbox to exercise this document.

## Operator prerequisites and incident record

Assign these incident roles:

- Incident commander.
- Database/recovery operator.
- Identity/key operator.
- Release reviewer.
  Record the deployment's exact service names, ingress controls, secret-manager access and escalation contacts in restricted operations documentation.
  An unfilled prerequisite is a deployment blocker, not permission to improvise production access or use a broadly privileged identity.

Record UTC detection/containment/recovery times, affected service classes, exact release/migration revisions, sanitized status/counts, action approvals and restricted evidence references.
Never attach private project bodies, prompts, tokens, cookies, decrypted keys or raw HTTP/database traces.
Use a dedicated synthetic workspace for drills.
Never deliberately corrupt production state.
Live ingress, replica, secret or key-policy changes require operator authority.
This document performs none.

## Database outage or connection exhaustion

1. Check `/health/live` and `/health/ready` separately.
   Process liveness does not prove database availability.
   Inspect connection counts, storage, locks and API/consumer errors through restricted monitoring.
2. Contain retry amplification at ingress.
   Pause canonical writers/consumers using deployment controls.
   Preserve authorized reads where safe.
   Feature flags are not a universal write pause: cover API mutations, consumers, maintenance and every replica.
   Never bypass authorization or give a worker database access.
3. Distinguish reachability/credentials, pool exhaustion, blocked transactions and storage failures.
   Increasing API replicas adds connections.
   Check the [pool budget and settings](DATABASE-POOLS.md) against actual process counts.
   Include rollout surge and maintenance headroom before changing scale.
4. Recover the existing service or follow [isolated recovery](RECOVERY.md).
   Do not reset/stamp the schema or drop a failed restore to make readiness green.
   Preserve evidence and failed targets.
   A client timeout does not prove transaction rollback.
5. Before resuming writes, verify readiness, selected authentication, cross-scope denials, exact public releases and restored canonical integrity where applicable.
   Resume consumers gradually.
   Check retry receipts and duplicate effects.
   Record backlog drainage separately from readiness.

## Key-service outage and credential rotation

1. Distinguish key metadata/TLS/token failures from provider failures using sanitized statuses.
   Do not enable wire logging or put real provider credentials in commands.
2. Pause migration/rotation on key failure.
   Preserve original envelopes, exact historical readers and retained key versions.
   Never fall back to local encryption in production, silently try another backend or weaken policy to force decryption.
3. The key operator restores the intended identity, trusted TLS and exact key/version availability.
   Recovery/unseal and backup-decryption material remain separately protected.
   Database ciphertext alone is not a usable key backup.
4. Use the synthetic-key [OpenBao gate](openbao/VERIFY.md) when selected, or the chosen AWS backend's approved equivalent.
   On an isolated restore, run the bounded [credential scan](RECOVERY.md#restored-artifact-and-credential-dependencies).
   A partial scan is not success.
5. Resume reviewed [migration](openbao/MIGRATION.md) only after old and target versions decrypt with the original context.
   Retain readers/keys required by older backups even when current rows have all migrated.

Provider credential rotation is separate from rewrapping its data key.
Use the authorized profile-rotation operation.
Retain its audit result.
Verify that the API denies old grants.
Actual provider acceptance requires an authorized deployment check.
Mocked gateway tests do not prove it.

## Privacy, identity or moderation incident

1. Contain the affected route/cohort at ingress if disclosure is suspected.
   Preserve audit evidence without copying private content to tickets.
   Do not erase immutable research/history as an incident-cleanup shortcut.
2. Revoke affected access/session through the configured provider's supported controls.
   Built-in logout, membership revocation, OIDC session revocation and provider-key rotation are distinct.
   None automatically substitutes for another.
   Do not change authentication mode or auto-link identities as a recovery action.
3. Use authorized public moderation.
   Verify that direct anonymous reads and search omit the affected content.
   Test private access with authorized and revoked/unrelated identities, including browser/SSE reconnects and cached views.
4. Verify selected-provider login/logout/expiry.
   The [staging probe](staging/README.md) does not prove revocation or browser cookie/CSRF behavior.
   OIDC tokens may remain valid until actual expiry/cache policy permits rejection.
   Record that boundary.
5. Reopen routes only after the security/release reviewer accepts negative access checks and containment evidence.

## SSE degradation or delayed notifications

1. Compare canonical API state with client-visible state before diagnosing data loss.
   Inspect readiness, proxy settings, reconnect rates and consumer backlog.
2. Verify `text/event-stream`, disabled buffering and deployment idle/read timeouts.
   Test `Last-Event-ID` reconnect with synthetic events, without logging private bodies.
3. Restore the proxy/consumer and observe bounded retries and receipt-based processing.
   Do not delete outbox events/receipts or advance cursors to conceal backlog.
   A process restart is not proof of successful canonical replay.
4. Verify expected ordering/replay, absence of duplicate durable effects and reauthorization after revocation.
   Record backlog age and recovery time separately from successful HTTP connection establishment.

## Application rollback without losing history

1. Identify the failing release, schema revision, flags and proposed known-good image.
   Pause affected admission before changing replicas.
   Keep optional execution disabled unless its acceptance gates have passed.
   Preserve stored jobs/results.
2. Confirm the older application supports the current schema and retained key/event formats.
   A Git rollback is not proof of compatibility.
   If compatibility is unproven, maintain containment.
   Prepare a reviewed forward fix instead of downgrading the database.
3. Use the approved rollout mechanism.
   Fence/drain incompatible consumers before resuming them.
   Retain revisions, publication releases, job history and audits.
   Recursive cleanup and schema resets are not rollback steps.
4. Verify readiness, selected authentication, cross-scope denials, exact historical reads and moderation.
   Resume paused execution admission with approval.
   Computation also requires accepted isolation and an authorized execution environment.

## Acceptance evidence

For each applicable scenario, record:

- Preconditions and approved fault.
- Expected failure and observed sanitized result.
- Containment and recovery verification.
- Elapsed time and remaining limitations.
  Attach exact service/code versions and reviewer sign-off.
  Missing evidence means **not exercised**, not passed.

Local regressions under `tests/backend/` include `test_local_auth.py`, `test_gateway.py`, `test_openbao_credentials.py`, `test_outbox.py`, `test_record_moderation.py`, `test_recovery_dependencies.py` and `test_staging_auth_probe.py`.
Their local/mocked behavior does not establish a live database, key, ingress, identity or recovery drill.
Execution scenarios remain separate and must not be silently omitted from deployment acceptance.

Recovery evidence must identify coordinated database/object/key backups, checksums, migration revision and timings.
Verify encrypted retention of at least 14 daily, 8 weekly, and 3 monthly recovery points.
Measure recovery on a live isolated restore.
Verify a database RPO of at most 24 hours.
Verify an RTO of at most 60 minutes.
Scripts and checksums alone do not prove those requirements.
