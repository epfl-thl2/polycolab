# Research schema

PostgreSQL is the canonical deployment database.
Local development uses SQLite with a separate migration history.
SQLAlchemy mappings live in [`backend/polycolab/db/models/`](../../backend/polycolab/db/models/).
Use the [database directory guide](../../backend/polycolab/db/README.md) to find models, stores, converters, and migrations.

This document describes the current storage boundaries.
The [research version contract](research-versions.md) defines application snapshots and wire behavior.
[object kinds and reviews](object-kinds-and-reviews.md) defines the current vocabulary and its historical encodings.

## Stored state

| Area                         | Responsibility                                                                                                                                |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Accounts and authentication  | Built-in accounts, digested browser sessions, registration invitations, immutable social identity bindings, and optional email recovery state |
| Workspaces                   | Public/private visibility, membership and roles, lifecycle, and ownership scopes                                                              |
| Research identities          | Stable object IDs, canonical kinds, authorship, and current-version pointers                                                                  |
| Research versions            | Complete immutable typed content, linear predecessor chains, semantic metadata, and contribution attribution                                  |
| Relationships                | Exact directed or symmetric endpoints. Structural members remain frozen with a version. Independent declarations retain their attribution.    |
| Contributions                | Human/agent provenance, typed outputs, scoped idempotency receipts, and transactional outbox events                                           |
| Reviews and research context | Exact-version assessments, dedicated human-note and authored-summary histories, progress, comments, and pinned workspace references           |
| Catalogue and publication    | Human admission, official source/status metadata, immutable released projections, selected publication closures, and moderation audits        |
| Artifacts                    | Scoped immutable identity and integrity metadata, exact research bindings, lifecycle, and separately stored bytes                             |
| Jobs and agents              | Session/run history, pinned context, finite budgets, claims, leases, fences, execution attempts, and result/evidence bindings                 |

Application entity names and physical table names need not match.
Some historical database encodings and compatibility projections remain so existing versions, receipts, and releases can be read without changing their meaning.
New API writes use the current canonical vocabulary.

## Integrity and transactions

Every research version belongs to one stable object and ownership scope.
Version numbers and predecessor links form a linear history.
Saving requires the expected current version.
Stale writes fail instead of overwriting newer research.
Advancing an object head never retargets an existing exact relationship or review.

PostgreSQL constraints and immutable-history triggers protect version content, structural membership, endpoint shapes, attribution, and public history.
Domain services enforce current actor, role, scope, and reference permissions inside the write transaction.
Request validation and ORM relationships do not replace these checks.
A raw application snapshot is not an authorized public projection.

Content changes, contribution outputs, mutation receipts, and outbox events commit together.
Receipt identity includes actor, operation, destination, and canonical payload.
Changed requests under the same retry key conflict.
Replays still check current authority.
Services acquire shared locks in their established order.
Authorization changes must serialize with the writes they govern.

Public releases retain immutable selected fields, exact version identity, and digests.
Publication checks the required dependency closure and excludes private context.
Hiding a resource changes its availability without erasing retained research, release, or audit history.

## Migrations and recovery

Supported PostgreSQL installations start at `20260905_baseline` and apply the complete Alembic chain to `head`.
Existing installations on this chain upgrade incrementally.
Databases from before that prototype reset are unsupported.
Do not stamp them as current or reset a configured database to make startup succeed.

```sh
pnpm run api:migrate
```

Run this command with the intended deployment configuration, as described in [deployment guidance](../../deploy/README.md).
Production migrations run once in a dedicated job.
Do not replace the baseline for routine feature changes.

The local launcher applies SQLite migrations and backs up existing databases under `.local/backups/`.
Local and Docker datasets remain independent.
Moving Python modules or documentation does not change stored Alembic revision IDs.

Use coordinated database, artifact, and key recovery.
A Git rollback does not establish schema compatibility.
Forward-only migrations can require restoration of a pre-upgrade backup with the matching application.
Follow the [recovery contract](../../deploy/RECOVERY.md) and [incident procedures](../../deploy/INCIDENTS.md).

## Verification

Database checks live in [`tests/backend/`](../../tests/backend/), including `test_m0_postgresql.py`, `test_relationships_postgresql.py`, `test_records_postgresql.py`, and the publication/recovery suites.
They cover fresh schema/ORM agreement, populated upgrades, immutable history, retry contention, stale edits, and permission changes against waiting writers.
Use the fixtures' disposable schemas.
SQLite checks do not establish PostgreSQL constraint or concurrency behavior.
See the [system test guide](../../tests/system/README.md) for combined service and restore verification.
