# Application entities and SQL persistence

Polycolab separates application data from persisted rows.
A research view may combine an object, revision, author, contribution, and several attachment rows.
An application entity does not have to correspond to one table.

## Ownership and dependency direction

- `src/backend/polycolab/entities/` contains application dataclasses and shared enum values.
  These modules do not import database adapters, SQLAlchemy, FastAPI, or HTTP schemas.
  Snapshots are immutable and have no lazy database access.
- Capability-local `store.py` modules define store Protocols.
  They accept application values and return materialized entities, with explicit operations for writes rather than a generic aggregate `save()`.
- Capability services own authorization decisions, invariants, and workflows.
- `src/backend/polycolab/transaction.py` defines transaction completion and savepoints shared by stores participating in one operation.
- `src/backend/polycolab/db/` implements the interfaces with SQLAlchemy.
  `models/` describes persisted rows.
  `stores/` owns SQL and lock acquisition.
  `converters/` explicitly constructs application values.
  Shared application enums retain their existing database encodings.
- HTTP schemas describe external validation and serialization.
  A transport `contracts.py` file is not an application-entity package.

Every SQLAlchemy mapped class, including query projections, uses the `Sql` prefix (for example, `SqlUser` and `SqlObjectRevision`).
Imports and exports retain that prefix.
Application entities keep their domain names.
The unmapped declarative `Base`, plain table variables, and shared enums are exempt.
Python class names are not persisted identifiers: research activity uses explicit stable source-kind strings so class renames preserve event identities and backfill retries.

Composition creates database adapters and injects the application interface.
Application services must not construct SQLAlchemy adapters themselves once converted.
There is no separate `ports/` package.

## Project vocabulary

Application code calls the resource `Project`.
`ProjectAccess` combines it with optional caller membership for listings.
`ProjectMemberAccess` combines it with required membership after authorization.
Both expose `.project`.
`ProjectPolicy`, `ProjectAction`, and `ProjectNotFound` use the same vocabulary.
Stores expose `project()` and `create_project()`.

Application creation uses `create_project()` too.

Public API schemas use `ProjectRole`, `ProjectVisibility`, and project request/response names.
Public fields and query parameters use `project_id`.
Project-scoped endpoints use `/api/v1/projects/{project_id}`.
The generated client and browser adapters use the same names.

The public API and current schema use `project_id` and Project terminology.
Request models reject obsolete Workspace fields; browser bookmark redirects do not alias API routes.
Forward PostgreSQL and SQLite migrations rename product metadata without changing identities or immutable history.
The historical adapter preserves known receipt operation names and canonical digest fields, and projects old grants and credential rights at read boundaries.
See the [Project cutover](external-agent-api.md#project-terminology-cutover) for deployment and compatibility requirements.

## Transactions

All stores in one SQL transaction share one session.
Store methods may flush to obtain generated identifiers or enforce constraints, but never commit.
The coordinating operation commits only after its changes are complete.
An uncommitted transaction context rolls back on exit.
The factory-created context also closes its session.
Savepoint failure rolls back the nested work without committing or discarding the outer transaction.

Existing HTTP request composition shares the request session with its transaction.
During conversion, existing SQL consumers can construct a borrowing adapter around that same session, preserving cross-capability atomicity.
Such adapters do not own session closure.
They are transitional call sites, not proof that those consumers have become database-independent.

Constraint violations become `PersistenceConflict`.
Other SQLAlchemy failures become `PersistenceError`.
Capability services translate conflicts into their existing domain errors where appropriate.
SQL error details are not added to HTTP responses.

Project authority locks retain the project-then-membership order.
Concurrent owner-set changes lock the project before reading owners.
Each policy check loads current membership.
Credentials do not cache membership.

## Migration ownership

`src/backend/polycolab/db/migrations/postgresql/` contains the Alembic environment, revision script template, and complete ordered version history.
`src/backend/alembic.ini` remains the CLI configuration entrypoint and resolves that directory relative to its own location.
Existing migration/deployment commands are unchanged.

Migration relocation does not alter version identifiers, SQL, schema state, or an existing database's Alembic version record.
Alembic imports the complete mapped-class registry before it examines metadata.
PostgreSQL triggers and other migration-defined integrity rules remain part of the schema even when they have no ORM counterpart.
Importing runtime code never applies migrations.

## Implemented and remaining conversion

The following operations have application boundaries:

- Identity synchronization.
- Built-in account creation.
- Password authentication.
- Browser sessions and registration.
- Project and membership authorization.
- Project creation.
- Membership and invitation operations.
- The shared paginated project listing.
  Project projections combine project and membership rows.
  Invitation snapshots omit persisted token digests.
  Actor and artifact values also live in the application entity package.
  Timestamp converters normalize UTC consistently across PostgreSQL and lightweight SQLite tests.

Research object/version and relationship snapshots now have application entities and a batch read store.
Stable identities load without version content.
Complete record reads and object history use materialized version snapshots.
Exact relationships have one canonical table, with read-only typed projections for existing proof/attempt/attachment consumers.
Write helpers share their caller's transaction and preserve structural insertion boundaries and attribution.
Research read stores translate SQLAlchemy failures through the same persistence error boundary as account and project stores.

Their batch queries load the rows needed by query-free, typed research converters.
Artifact and verification workflows share one artifact converter, including UTC timestamp normalization.
Relationship write helpers remain internal SQL adapters used by the unconverted mutation services.
They are not application store interfaces.
Research authorization, metadata projection, and mutation services still contain SQL access.
This is a read-boundary conversion, not complete research persistence isolation.

See [research versions](research-versions.md).

Artifact cleanup is a complete converted workflow.
`artifacts/cleanup.py` owns expiry policy, lifecycle transitions, and transaction completion through `Transaction.artifacts`.
`db/stores/artifacts.py` loads locked rows and performs writes, returning immutable artifact values.

Claiming retains UUID pagination and `SKIP LOCKED`.
The claim transaction closes before byte deletion.
The cleanup workflow records each successful deletion in a separate transaction.
Tombstones remain eligible for repeated deletion to handle late uploads.

`artifacts/gc.py` composes the adapters and runs the cleanup loop.
Upload, attachment, and public artifact workflows still use SQL directly and remain separate conversion work.

The service-wide isolation design is **not yet fully implemented**.
Research, catalogue, hosted/external agents, verification/execution, credential management, account recovery and social enrollment, and operational workflows still contain direct ORM access.
Some HTTP handlers also retain SQL reads and workflow coordination.
These must be converted through explicit stores and application entities.
Moving them wholesale into `db/` would incorrectly move business policy there.

The remaining work must preserve these properties:

- Immutable revisions.
- Exact public/private projection rules.
- Contribution and outbox atomicity.
- Idempotent retries.
- Lock ordering.
- Intentional transaction phases.
- The worker's API-only boundary.

## Verification

Static checks protect application entities, converted services, store interfaces, model dependencies, and the private-worker boundary.
Adapter tests cover multi-table snapshots after session closure, rollback, savepoints, constraint translation, and omission of private persistence fields.
PostgreSQL tests cover fresh migration/metadata agreement, integrity and stale writes, concurrent owner demotion, and rollback across account/project stores.
HTTP contract checks ensure generated OpenAPI/client output remains current.

## Docker-free local development

`pnpm run dev:local` selects `.local/polycolab.db` and filesystem artifacts under `.local/artifacts/`.
This is a single-API-worker development mode, not a production database substitute.
Docker remains PostgreSQL plus Garage, with independent data.

SQLite uses a separate Alembic history under `src/backend/polycolab/db/migrations/sqlite`.
The frozen baseline contains schema and required system seeds.
Startup never uses `metadata.create_all()` to upgrade a user database.
Add a SQLite revision alongside each schema change.
Keep the migration/model parity test passing.

Before an upgrade, the local launcher creates backups of existing SQLite files with SQLite's backup API.
Upgrades run inside an explicit transaction.
Unknown or unversioned databases fail closed.
Downgrades are not automatic: stop local mode and restore a verified backup.

Preserve artifacts together with the database when moving or backing up the local directory.

Persistent SQLite enables foreign keys, WAL and a bounded ten-second lock wait.
Runtime connections use sqlite3's non-legacy transaction mode so releasing a savepoint cannot commit independently of the outer transaction.
The connection setup temporarily configures PRAGMAs outside the transaction.
It follows the [SQLAlchemy SQLite guidance](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#enabling-non-legacy-sqlite-transactional-modes-with-the-sqlite3-or-aiosqlite-driver).

Regression tests exercise first-write savepoints with explicit commits, rollbacks, exceptions, and uncommitted exits against memory and file databases.
PostgreSQL-specific locking and immutable-history triggers still require PostgreSQL integration checks.
Local mode is not evidence for production concurrency.

Filesystem artifacts implement the same bounded verification and authorization flow as Garage.
Opaque keys, exclusive writes, atomic publication and no-follow reads prevent overwrites and direct path access.
Cleanup deletes only domain-claimed staging objects, including interrupted temporary files for the same reserved key.
