# Protected non-execution telemetry

The existing `/internal/v1/metrics` endpoint remains disabled by default.
When `OPERATOR_DIAGNOSTICS_ENABLED=true`, it still requires an authenticated subject listed in `OPERATOR_DIAGNOSTICS_SUBJECTS`.
Enabling the flag does not make it a public Prometheus endpoint.
Retain restricted ingress, normal identity validation and no-store responses.
Do not put operator tokens in command arguments or logs.

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
