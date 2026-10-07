# Recovery implementation and verification

## PostgreSQL backup bundles

`scripts/backup-postgres.sh` creates a private, unique directory for each run.
In staging/production, an explicit age recipient is required.
`pg_dump` streams directly into age, so the script creates no intermediate plaintext database dump.
Local-only unencrypted output remains available when no recipient is supplied.
Files are mode 600 and each run directory is mode 700.

A successful bundle contains:

- `postgres.dump.age` (or `postgres.dump` for unencrypted local use).
- The adjacent `.sha256` checksum, using a relocatable relative filename.
- `COMPLETE`, written only after both pipeline commands and checksum succeed.

Only bundles with `COMPLETE` are candidates for retention/restore.
When the script catches a command failure, it removes only that invocation's files.
It never prunes earlier backups.
After an uncatchable kill or machine failure, incomplete directories may remain.
The marker is not a filesystem durability guarantee: external durable storage, checksum verification and a successful restore drill remain necessary.
A checksum detects corruption but does not authenticate an attacker-controlled manifest.

Verify a copied bundle before decrypting or restoring it:

```sh
uv run --directory backend python -m polycolab.backup_bundle /private/recovery/polycolab-backup-bundle
```

The read-only verifier requires the exact v1 marker, one archive, and its checksum.
It rejects these conditions:

- Extra or missing files.
- Symlinked or hard-linked members.
- Malformed checksums.
- Empty archives.
- Detected changes during streaming.

It never follows a filename supplied by checksum content.
`CHECKSUM_VERIFIED` proves byte integrity against the adjacent checksum, not source authenticity, successful decryption or restorability.
Use an operator-controlled bundle directory with no active writers.
Verification does not lock the archive against later changes.
Keep source manifests separately, not as extra files inside this three-file bundle.
No data is deleted by this check.

Prefer an explicitly configured libpq service (`PGSERVICE`, `PGSERVICEFILE`, and an appropriately protected password file) with `DATABASE_URL` unset.
This avoids placing the connection URL/password in pg_dump's process arguments.
Legacy `DATABASE_URL` remains supported but has that process-list exposure.
Configuring both modes is rejected.
Keep all credential files outside the repository.

Select the backup directory as the script argument.
Supply environment values through the operator's secret-management mechanism.
The script suppresses upstream stderr because it can contain private database details.
Failures use normalized messages.
This also means pg_dump warnings are not retained by this script.
Diagnose failures only in an access-controlled session, without publishing raw diagnostics.

Protocol references: [PostgreSQL custom-format/stdout dumps](https://www.postgresql.org/docs/18/app-pgdump.html), [libpq connection services](https://www.postgresql.org/docs/18/libpq-pgservice.html), and [age streaming encryption](https://github.com/FiloSottile/age/blob/main/doc/age.1.html).
Use supported, operator-pinned tool versions.
No new live tool-version acceptance is claimed here.

## Coordinated recovery sets

`bash deploy/scripts/backup-recovery-set.sh BACKUP_DIRECTORY` captures the encrypted database, cold Garage directories and retained key material.
Supply `PGSERVICE`, `BACKUP_ENCRYPTION_RECIPIENT`, `RELEASE_SHA`, `RECOVERY_SCHEMA_HEAD`, `RECOVERY_GARAGE_METADATA_DIR`, `RECOVERY_GARAGE_DATA_DIR` and `RECOVERY_KEY_MATERIAL_DIR`.
The script requires `RECOVERY_WRITERS_QUIESCED=yes` and `RECOVERY_GARAGE_STOPPED=yes`.
Stop canonical writers and Garage before setting these acknowledgments.
It retains incomplete captures for inspection.

Use `python -m polycolab.recovery_set --help` for isolated staging and verification.
Staging never activates a restore.
Preserve restored-cohort credential invalidation, artifact digest checks and key-service recovery before re-enabling ingress.
The research and key restore harnesses exercise local recovery boundaries.
Real recovery timing, external key services, and target-host drills remain deployment gates.

## Remaining recovery deployment gates

The PostgreSQL bundle is **database-only**.
The coordinated capture helper also packages Garage and retained key material.
Neither helper alone establishes an accepted Polycolab recovery point.
Deployment acceptance still requires these checks:

1. Bind the database snapshot/migration revision, canonical Garage bytes and retained key-service versions into a recovery set.
   Keep recovery/unseal and backup-decryption material separately protected and independently available.
2. Restore onto an explicitly isolated target.
   Verify immutable revisions, relations, provenance, historical results and exact public releases.
3. Verify every selected canonical artifact's authorized retrieval and digest.
   Verify credential decryption without logging plaintext.
   Rebuild disposable caches/indexes rather than treating them as canonical backup content.
4. Measure RPO ≤24 hours and RTO ≤60 minutes.
   Record actual timestamps, failure evidence, retention coverage, application/browser checks, and rollback.

The existing restore script remains limited to explicitly named local drill databases.
Restore/drill URLs reject query and fragment overrides and require a single database path, so libpq overrides cannot redirect a validated target.
Archive listing and a successful unambiguous target-existence query are required before any create/drop operation.
A failed restore leaves any partial database for explicit inspection.
The drill never automatically drops a target when its restore step failed (including a preexisting-name collision).
Successful drills retain the existing exact-name cleanup and `KEEP_RESTORE_DB=1` option.

The automated fake-tool tests prove pipeline failure handling, permissions, concurrent-run separation and absence of an intermediate dump.
They do not prove real encryption, PostgreSQL restoration or deployment recovery.

## Canonical database integrity manifest

The integrity verifier supplies a keyed, content-free comparison for canonical database state.
It streams every non-derived model table in primary-key order.
It emits only these values:

- Row count and HMAC-SHA-256 for each table.
- Exact Alembic revision.
- Explicit list of excluded rebuildable/operational projections.

No row value, identifier, credential field or ciphertext appears in the manifest or comparison report.

Pause admission before capture.
Pause all canonical writers before capture.
Maintain the pause during source-manifest generation and `pg_dump`.
Otherwise, the operations can observe different committed states.
A mismatch then does not establish a restore failure.

Supply a fresh `RECOVERY_MANIFEST_HMAC_KEY` through the operator secret mechanism.
Use at least 32 bytes.
Retain it separately from the backup.
Capture refuses to overwrite an existing file and creates it with mode 600:

```sh
uv run --directory backend python -m polycolab.recovery_integrity capture --output /private/recovery/source-manifest.json
```

After restoring, point the operator's `DATABASE_URL` at the isolated restore.
Use the same manifest key:

```sh
uv run --directory backend python -m polycolab.recovery_integrity compare --expected /private/recovery/source-manifest.json
```

For an integrated local drill, pass `--manifest /private/recovery/source-manifest.json` to `scripts/verify-restore.sh`.
It overrides `DATABASE_URL` for the comparison to the exact newly restored database and runs the locked backend module.

The source manifest and its separately supplied key must come from the same paused recovery point as the dump.
Omit this option only for the existing metadata-only smoke test.
That mode does not compare canonical rows.
Any restore, metadata-check or manifest comparison failure now retains the drill database for explicit inspection.
Only successful verification permits exact-name cleanup (unless `KEEP_RESTORE_DB=1`).

Manifest-backed drills now also run `recovery_dependencies research` after the canonical comparison and before cleanup.
The default semantic-scan bound is 1000.
Pass `--research-max-items N` (1–1,000,000) to change it.
That option also enables the semantic check without a source manifest, but does not then prove source/restore equality.
Both commands receive the exact isolated target through `DATABASE_URL`.
No caller-supplied source URL is reused for verification.

A semantic mismatch, partial scan, unavailable module or runtime failure preserves the drill database.
Invalid bounds fail before any database operation, including in dry-run mode.

With neither option, the existing metadata-only smoke check remains available and does not claim canonical or semantic recovery.
These fake-tool script tests prove command ordering, bounds and cleanup gating—not a live restore or RPO/RTO.

The comparison returns `MATCH`, or `MISMATCH` with schema/table names only.
It uses a PostgreSQL repeatable-read, read-only transaction and caps manifest files at 2 MiB.
A match proves exact database rows for the captured canonical tables.
It does not prove Garage object bytes, external key availability, rebuilt projections, application behavior, or backup authenticity.
Verify those separately before lifting the write pause or claiming a recovery drill.

## Restored research semantic verification

After the exact canonical manifest matches, interpret the restored research rows through the current application model.
The read-only verifier checks these relationships:

- Each stable object's latest revision pointer and base chain.
- Exact relation endpoints and scope.
- Human/agent contribution attribution.
- Public-field digests and publication membership.
- Human attribution of endorsement/correspondence history.

Run the verifier:

```sh
uv run --directory backend python -m polycolab.recovery_dependencies research --isolated-restore --max-items 100000
```

The explicit limit covers the combined objects, revisions, relations, publication manifests/members, public releases and assurance rows.
`LIMIT_REACHED` does not establish verification of any prefix.
It is not success.
Raise the bound only after sizing the isolated restore.
Output contains only a status, checked count and fixed failing section names such as `revision_chains` or `public_releases`, never IDs, titles, bodies, actors or release fields.
PostgreSQL transactions are read-only and the restored environment must remain quiescent.

`VERIFIED` proves that those application-level relationships are coherent under the current schema and projection digest algorithm.
It does not replay writes, prove database-trigger immutability under mutation, verify artifact bytes or keys, or establish that authorized browser/API reads succeed.
The restore driver invokes this check after manifest comparison, or independently when `--research-max-items N` is supplied, as described above.

## Restored artifact and credential dependencies

After canonical database comparison, check the corresponding restored Garage bucket and key services.
Supply the isolated database, restored object-store endpoint and read-only storage credential, and exact historical key-reader configuration through the operator environment.
Do not enable application or agent writers during these checks.

```sh
uv run --directory backend python -m polycolab.recovery_dependencies artifacts --isolated-restore --max-items 1000
uv run --directory backend python -m polycolab.recovery_dependencies credentials --isolated-restore --max-items 1000
```

Alternatively, opt into these checks in `scripts/verify-restore.sh` using `--artifacts-max-items N` and/or `--credentials-max-items N`, together with `--isolated-dependencies`.
Each bound is independently required and must be 1–1,000,000.
The acknowledgment confirms that the configured storage/key services are the quiescent isolated restore, read-only credentials are selected and writers are disabled.
It is an operator assertion, not automatic isolation verification.

The driver overrides only `DATABASE_URL` to its exact newly restored local database.
It does not discover, clone or redirect storage/key endpoints.
Configure those through the operator environment before opting in.
No credential or endpoint is supplied as a new script argument.

Selected checks run in order: metadata, optional canonical manifest, enabled research semantics, enabled artifact bytes, enabled credential decryption.
All must succeed before exact-name database cleanup.
A failed or incomplete dependency scan retains the database, and `KEEP_RESTORE_DB=1` also retains successful drills.
Private module stderr is suppressed.
Only its bounded report and a fixed failure message are emitted.

`--manifest` alone does not opt into external dependency reads, and dependency-only checks do not prove source/restore database equality.
Invalid bounds or missing isolation acknowledgment fail before any restore work, including in dry-run mode.
Fake-tool tests prove these ordering/target/cleanup rules, not real storage or key restoration.

Each command returns only a status and checked count.
Artifact verification reads all committed object identities and checks exact lengths and SHA-256 through the existing bounded Garage adapter.
It excludes uncommitted staging/GC objects.

Credential verification decrypts all retained profiles, including soft-deleted ones, with their original owner/profile binding and exact version-routed reader.
The verifier discards plaintext.
It never reports plaintext or sends it to a model provider.
This is not secure memory erasure.
No rewrap, key rotation, object mutation or database write is performed.
Key services may independently record their normal access audits.

Reads use pages of at most 100 rows and close each database transaction before storage/key-service calls.
PostgreSQL sessions explicitly use read-only transactions.
The operator must keep the isolated restore free of active writers across all pages.
This command does not pause writers or provide a cross-service snapshot.
`--isolated-restore` acknowledges that precondition.
It cannot prove isolation.

`VERIFIED` means this dependency scan reached its end.
`LIMIT_REACHED` exits nonzero and is not success.
Select an adequate explicit bound (maximum 1,000,000).
Rerun from the beginning.
Failures stop at the first dependency or database error with only the successful count.
There is no secret-bearing diagnostic or public cursor.

Transport phase timeouts are inherited from the adapters, not a guaranteed total drill deadline.
Record elapsed time separately for RTO evidence.

These operator scans do not replace application-authorized artifact download, login/publication/browser tests, archive decryption/restore, key backup restoration, retention coverage or RPO/RTO measurement.
Their local tests use SQLite, fake S3, and local cryptography.
They do not establish real Garage/OpenBao recovery.
