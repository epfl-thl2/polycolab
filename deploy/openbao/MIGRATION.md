# Operator credential migration

Apply the migration chain through `20260908_credential_rewrap_audit` before using this command.
Configure `KMS_PROVIDER=openbao`, the active target and every required historical reader.
Keep the API and operator configuration consistent.
This is a trusted operator process with database/key-service credentials, never a worker, browser action or API-startup task.
It does not provision keys or change policies.

First inspect one bounded page without key-service calls or credential writes:

```sh
uv run --directory backend python -m polycolab.credential_rewrap --limit 100
```

Verify backups, reader compatibility, and live key checks before applying one page.
Replace the example target with the exact configured envelope version.
The command refuses a mismatch before opening the database:

```sh
uv run --directory backend python -m polycolab.credential_rewrap --apply --limit 100 --expected-target-version openbao:v1:primary:production:transit:gateway:2
```

The default is a read-only count, not a decryption-readiness check.
Each invocation selects at most 100 non-deleted profiles whose envelope differs from the target.
It closes the read session and verifies each rewrap outside transactions.
It then compares the original owner/version/envelope.
It commits the replacement and audit atomically.
The command retains provider ciphertext and credential version.

Reports contain only counts, a fixed status and `more_may_remain`.
They do not expose profile IDs, ciphertext, fingerprints or credentials.
A full page means more records may remain, not that a second page is known to exist.
Concurrent writes can change that assessment.
Operational logs must not enable SQL parameter or HTTP body tracing.

The command stops on the first key, concurrent-change or database failure and exits nonzero.
Earlier successful records stay committed.
Investigate the normalized failure in an access-controlled environment.
Rerun from the beginning.
The command skips rows already at the target version.

The canonical envelope and immutable audit are the durable per-record checkpoint.
No external cursor file is required.
An ambiguous post-commit error may undercount `migrated` in the current report.
A rerun reads state again.
It does not blindly repeat the replacement.

Do not remove old readers or raise minimum decryption versions based solely on an empty page.
Verify retained backups and restore compatibility first.
Configure every required prior Transit version through the bounded historical-version list.
Retain the optional legacy AWS reader while those envelopes or recoverable backups exist.

Automated orchestration coverage uses SQLite and local cryptographic wrappers.
It does not establish migrated PostgreSQL contention, live AWS/Transit behavior, backup restorability or permission to migrate an existing deployment.
Command tests do not migrate existing deployment credentials.
