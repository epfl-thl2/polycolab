# Protected non-execution telemetry

The existing `/internal/v1/metrics` endpoint remains disabled by default.
When `OPERATOR_DIAGNOSTICS_ENABLED=true`, it still requires an authenticated subject listed in `OPERATOR_DIAGNOSTICS_SUBJECTS`.
Enabling the flag does not make it a public Prometheus endpoint.
Retain restricted ingress, normal identity validation and no-store responses.
Do not put operator tokens in command arguments or logs.

## Implemented community outbox snapshot

An authorized scrape includes:

- `polycolab_outbox_pending_events{consumer="community"}`
- `polycolab_outbox_oldest_pending_age_seconds{consumer="community"}`
- `polycolab_operational_snapshot_total{source="community_outbox",outcome="success|error"}`

Pending means no completed `community_delivery_cursors` entry exists for the canonical event.
Generic outbox receipt status is not community completion.
The snapshot reads only counts and minimum timestamps.
It never selects payloads or identifiers or adds them as labels.
Empty backlog has zero age.

The count remains meaningful when catalogue consumption is disabled.
Events can remain pending until an authorized rollout enables that consumer.

Each request takes a short read transaction.
PostgreSQL uses read-only mode and the shared one-second transaction-local statement timeout.
The transaction closes before publication/rendering.
A snapshot failure omits both gauges and increments only the fixed error counter.
It returns no stale value or false zero.
Successful later scrapes republish gauges.

Durable-metric reads remain a separate dependency.
The HTTP scrape can still fail when the entire database is unavailable.

The backlog gauges describe the same canonical database on each API replica.
**Do not sum those replicated snapshots**.
Select one representative successful scrape or deduplicate by database deployment identity in the monitoring system.
Snapshot success/error counters are process-local, restart with the API and may be aggregated as rates across compatible processes.
The application adds no deployment, tenant or per-request identifier labels.
Concurrent requests publish and render their own completed snapshots under a short in-process lock, never holding that lock across SQL.

## Database-pool lifecycle observations

The API's protected scrape includes its own PostgreSQL pool configuration, current checked-out count, acquisition duration (`_count`, `_sum`, `_max`) and `acquired`/`timeout` outcomes.
The scrape uses only the fixed `role="api"` label.
Timing wraps SQLAlchemy's public pool acquisition boundary and includes queue waiting, connection creation and pre-ping.
It is not pure queue wait or SQL execution time.
Non-timeout connection errors propagate unchanged and are not counted as pool timeouts.
The observations execute no SQL and retain no connection identity.

Counters survive pool recreation within the process, but reset on process restart.
The checked-out gauge reads the engine's current pool, including correct returns, invalidation and detachment.
After engine disposal it does not count outstanding connections from the retired pool.
SQLite retains its existing pool behavior and does not advertise these PostgreSQL pool budgets.
Each API app owns its registry.
These are not fleet-wide saturation observations.

Sample the gauge over time.
An instantaneous zero does not rule out earlier contention.

## Standalone community-process export

The standard monolith runs notification processing inside core and reports its
shared pool under `role="api"`. No community socket or extra consumer is needed.
The standalone command remains available for isolated diagnostics; do not run it
alongside core.

The standalone community consumer exports its own `role="community"` pool observations only when explicitly launched with `--metrics-uds /absolute/private/path/metrics.sock`.
The directory must meet these conditions:

- It already exists.
- The process UID owns it.
- It has mode 700.
- Its canonical path has no symlink components.

The exporter creates the socket with mode 600.
It refuses existing paths, including stale sockets.
It never removes those paths.
Normal shutdown removes only the socket created by that invocation.
After a crash, confirm that the owning process stopped before removing its stale socket.
The application never creates a host directory or changes its ownership for this purpose.

The consumer runs without a product feature flag.
Its optional exporter requires `OPERATOR_DIAGNOSTICS_ENABLED=true`, with a nonempty `OPERATOR_DIAGNOSTICS_SUBJECTS` list.
Without `--metrics-uds`, even enabled operator diagnostics do not start a listener.
The service opens no TCP port.
It serves only the existing `/internal/v1/metrics` path, with no login/setup, application or API documentation routes.

Disabled diagnostics return 404.
Missing/invalid identities return 401, non-operators 403, and identity/pool failures a sanitized 503.
Application responses are no-store/nosniff.
The exporter rejects request bodies and disables access logging.
It never logs credentials or arbitrary request paths.

Use the same selected authentication settings as the API.
Built-in mode validates the operator's opaque session cookie against the same canonical database, including expiry/revocation.
It does not accept a session as a bearer token.
OIDC mode uses the existing configured issuer/JWKS verifier.
The allowlist contains verified subject values (built-in account UUIDs), not usernames, email addresses or a new shared monitoring password.

Cookie/token provisioning, expiry and refresh remain operator responsibilities.
Never put credentials in command arguments or logs.

The consumer and exporter share one instrumented engine and pool.
Authentication transactions close before pool rendering.
No second pool or cross-process registry is introduced, and the API does **not** export these community observations.
Pool exhaustion may cause database-backed authentication to return 503.
An unavailable scrape does not establish an empty pool.
There is one consumer thread and one bounded HTTP server per process.

Shutdown stops admission to the listener and signals the consumer.
It waits for the current consumer transaction before disposing the engine.
It does not impose a hard deadline on already blocked SQL.
Use the deployment's database statement limits and process termination policy for that separate bound.

The optional [Compose override](observability/compose.yaml) enables operator diagnostics
on the core application's existing protected metrics endpoint. It starts no separate
consumer and requires no Unix socket directory. Supply the verified operator subjects
through `OPERATOR_DIAGNOSTICS_SUBJECTS`.

The following socket guidance applies only to the standalone diagnostic command.

A scraper/proxy must have local socket access under the same trusted UID or an equivalently protected shared-volume arrangement.
It must also present a valid operator identity.
Any network-facing proxy needs restricted ingress, TLS, no caching (including server-generated errors) and credential-safe logging.
Do not publish an unauthenticated proxy or give the database-free agent worker database credentials to bridge monitoring access.
Use a distinct socket directory per consumer replica.
Attach deployment/process identity in the monitoring system.

This uses Uvicorn's [programmatic server lifecycle](https://www.uvicorn.org/) with an application-bound private socket.
The command does not enable reload or multiple server workers that could duplicate the consumer.

## Remaining work and evidence

Actual scraper/proxy deployment and measured saturation remain pending.
Execution queue/resource/cache telemetry remains deferred with the runtime.
Local checks do not establish acceptance of a public listener, deployed container, or execution runtime.

Tests in `test_operational_scrape.py` cover protected-route denial, content-free success, cumulative outcomes, stale-gauge removal/recovery and transaction close before publishing.
Shared `test_operational_telemetry.py` covers cursor semantics, labels and the opt-in PostgreSQL/index/timeout foundation.
Local SQLite checks do not prove production query latency or operational capacity.
Exercise the actual target with representative backlog and monitoring retention before acceptance.

`test_pool_telemetry.py` exercises a real SQLAlchemy QueuePool with SQLite DBAPI.
It covers acquisition, bounded timeout/recovery, concurrent return, invalidation, detachment, pool recreation, error propagation, registry isolation, and protected API export.
It does not constitute live PostgreSQL or multi-process deployment evidence.

`test_community_metrics.py` checks denied/sanitized responses, private socket ownership/cleanup, defaults without a listener, and disposal after startup failure.
It also checks a short-lived real Unix-socket HTTP exchange with database-backed local-session revocation and consumer shutdown.
A real consumer subprocess also exits cleanly and removes its socket after SIGTERM.
These checks use SQLite, not a deployed PostgreSQL consumer, real OIDC issuer or production monitoring integration.

API contract: [non-execution telemetry](../docs/architecture/api.md#non-execution-operational-telemetry-foundation).
