# PostgreSQL connection budgets

Each application process that uses the database has a finite connection pool.
Application settings do not discover replica counts or reserve connections globally.
No application setting increases the PostgreSQL server limit.

| Setting                         | Default | Accepted range                            |
| ------------------------------- | ------- | ----------------------------------------- |
| `DATABASE_POOL_SIZE`            | 5       | integer 1–1000                            |
| `DATABASE_MAX_OVERFLOW`         | 5       | integer 0–1000                            |
| `DATABASE_POOL_TIMEOUT_SECONDS` | 30      | finite number greater than 0, at most 300 |

Each process can hold at most size + overflow connections.
The timeout bounds pool acquisition wait, not statement execution, DNS, a whole HTTP request or transaction lifetime.
Do not keep transactions open during provider, key-service, storage, or execution I/O.
SSE clients and sandboxes must not each acquire a dedicated pool.
These settings do not change SQLite's in-memory `StaticPool`.

## Deployment calculation

Count every process that uses the database at maximum simultaneous scale:

- API worker processes per replica.
- Extra processes during rolling updates.
- Consumers and batch jobs.
- Other applications that share the database server.

The private worker/controller has no database URL or pool and must remain outside this connection count.
Alembic uses a separate `NullPool`.
Reserve maintenance connections for migrations, backup/restore jobs and approved operator access rather than omitting them.

Ask the database operator to inspect the actual server settings:

```sql
SHOW max_connections;
SHOW reserved_connections;
SHOW superuser_reserved_connections;
```

Subtract both reserved settings from the application ceiling.
Do not grant the application privileged reserved-slot access.
Keep an additional explicit allowance for maintenance and other known clients.
Managed-platform or role/database limits may be tighter than the server ceiling and require separate checks.
Do not assume the stock PostgreSQL default is the deployed value.

Run the offline preflight with one repeated `--pool PROCESSES SIZE OVERFLOW` per process class.
This example represents four API processes (including any surge) and two serial consumers on a **hypothetical** 100-connection server:

```sh
uv run --directory backend python -m polycolab.database_budget \
  --server-limit 100 --reserved 10 --headroom 10 \
  --pool 4 5 5 --pool 2 2 0
```

The example budgets 44 application connections, 10 reserved, 10 maintenance and 36 unallocated.
The command exits nonzero for invalid declarations or a total that reaches or exceeds the server ceiling.
`CONFIGURATION_FITS` is arithmetic over operator declarations, not discovery of actual settings, live saturation evidence or automatic admission control.
It opens no database connection and reads no deployment credentials.
Recalculate before scaling or rolling out a changed pool.

## Compose and environment examples

Compose budgets its processes as follows:

| Process            | Pool size | Overflow | Maximum connections |
| ------------------ | --------- | -------- | ------------------- |
| API                | 5         | 5        | 10                  |
| Community consumer | 2         | 0        | 2                   |
| Hosted reconciler  | 2         | 0        | 2                   |

All three processes together can use at most 14 application connections.
Pools acquire connections lazily.
This is an upper bound, not a claim that all are open.
The disabled catalogue consumer exits without creating its engine, but budgeting its enabled maximum prevents a flag change from silently invalidating the plan.

Override Compose interpolation variables per service using `POLYCOLAB_API_DATABASE_POOL_SIZE`, `POLYCOLAB_API_DATABASE_MAX_OVERFLOW`, `POLYCOLAB_API_DATABASE_POOL_TIMEOUT_SECONDS`, and corresponding `POLYCOLAB_COMMUNITY_...` names.
Staging/production environment templates provide the generic application names above.
Set consumer-specific values in the actual deployment.
Neither template is a measured production capacity recommendation.

Use configuration inspection to check these values.
Keep the optional execution profile disabled until its acceptance gates pass.
Configuration inspection and the offline preflight need no running service.

## Acceptance boundary

The disposable PostgreSQL exhaustion/release test is in `tests/backend/test_database_pool.py`.
It demonstrates a one-process finite wait and recovery after connection release.
Run it against an operator-approved isolated database with `M0_POSTGRES_TEST_URL`.
A missing URL skips the live case.
Arithmetic and configuration regressions do not replace that evidence.

Deployment acceptance still needs the real ceiling/role limits, peak replica inventory, observed connection saturation, timeout/error recovery, interactive latency and backlog behavior.
Record hardware, dataset, concurrency and rollout surge.
Do not raise pool or server limits to conceal a connection leak or a long transaction.

References: [PostgreSQL connection/reserved-slot settings](https://www.postgresql.org/docs/18/runtime-config-connection.html) and [SQLAlchemy pool limits and timeouts](https://docs.sqlalchemy.org/en/20/core/pooling.html).
