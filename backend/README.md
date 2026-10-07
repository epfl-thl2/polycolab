# Polycolab API

FastAPI owns Polycolab's application API, research authorization, durable agent runs, proposal review, and private worker gateways.
Authorized agents can save scoped research contributions directly.
The worker has no database credential.
Claims and every canonical state mutation cross the authenticated private Runtime API.

## Application layout

HTTP handlers live in capability-local `routes/` packages.
Application startup and router composition live in `polycolab/app/`.

`polycolab/entities/` contains application data classes and shared values.
`polycolab/db/` owns SQLAlchemy models, engine/session setup, store implementations, row converters, and the Alembic environment and version scripts.
The complete model registry is `polycolab.db.models`.
Import it before inspecting `polycolab.db.base.metadata`.

Capability-local `store.py` modules define database-independent interfaces.
`polycolab/transaction.py` defines the shared transaction interface, implemented by `polycolab/db/transaction.py`.
Identity synchronization, built-in accounts, browser sessions, registration, project authorization, workspace operations, and the shared workspace listing use these interfaces.
Other capability services still use SQLAlchemy directly during the conversion.
See [persistence architecture](../docs/architecture/persistence.md).

Run migrations through the root command `pnpm run api:migrate`.
`backend/alembic.ini` resolves its migration location relative to itself, and runtime imports never run migrations.
Capability services own business rules.
Stores perform explicit reads and writes in the caller's transaction.

## Authentication

Built-in accounts (`AUTH_MODE=local`) are the default in every environment.
For an empty database, set `BOOTSTRAP_ADMIN_PASSWORD`.
The deployment command creates the fixed `admin` account after migrations and before serving requests.
The browser has no administrator-setup endpoint.
Subsequent requests use an HTTP-only, opaque database-backed session cookie.

The API stores password verifiers and session digests in PostgreSQL.
It never stores raw passwords or session tokens.

Built-in mode can also offer direct Google and GitHub sign-in.
Each enabled provider requires an exact `PUBLIC_APP_ORIGIN` and a complete client-ID/secret pair.
These server-side adapters use durable single-use, browser-bound state and stable provider subject identifiers.
The adapters never store provider tokens or return them to the browser.

Social enrollment starts only after administrator bootstrap and creates normal non-admin accounts.
It never links by email, display name or username.
See the explicit [browser contract](../docs/architecture/api.md#built-in-social-auth-browser-contract).

Operators may instead use `AUTH_MODE=oidc` and configure the issuer, JWKS URL, browser client ID, and audience.
Use HTTPS before public exposure.
In built-in mode, initialize the administrator before public exposure.
See the [deployment safeguards](../deploy/README.md).
Organizational OIDC identities and built-in local/social accounts remain separate authentication adapters.
After authentication, Polycolab's project authorization policy applies.

## Operations

Set deployment configuration through environment variables.
Do not place any provider key in this file, logs, events, or diagnostic output.
PostgreSQL-backed admission state enforces the execution safety controls.
These controls use conservative defaults:

- Owners control public/private workspace visibility.
  Deployment flags do not select visibility.
- `FEATURE_AGENT_EXECUTION_ENABLED` gates session creation, queueing, and resume requests.
- `EXECUTION_USER_REQUESTS_PER_MINUTE`, `EXECUTION_PROJECT_REQUESTS_PER_MINUTE`, `EXECUTION_USER_CONCURRENT_RUNS`, and `EXECUTION_PROJECT_CONCURRENT_RUNS` bound admission.
- `EXECUTION_USER_DAILY_TOKENS`, `EXECUTION_PROJECT_DAILY_TOKENS`, `EXECUTION_USER_DAILY_COST_MICROUSD`, and `EXECUTION_PROJECT_DAILY_COST_MICROUSD` are daily caps.
  Active runs reserve the configured maximum input and output for every allowed model round and recovery attempt.
  These are safety ceilings, not invoices or exact provider billing.
  The Runtime API rechecks the database budget before each model round.
  It fails closed unless the budget permits the next bounded round.
- `EXECUTION_MAX_INPUT_TOKENS_PER_ROUND` must cover `GATEWAY_MAX_INPUT_BYTES`.
  The default reserves one token per byte.
  `RUNTIME_MAX_MODEL_ROUNDS` and `RUNTIME_MAX_ATTEMPTS` determine each active run's reservation.
- `EXECUTION_RATE_WINDOW_RETENTION_MINUTES` controls cleanup of old minute buckets.
  The Runtime API deletes them in indexed, bounded batches during claims.
  Retain enough history for short operational investigations.
  Do not preserve these buckets as analytics data.
- `PUBLIC_READ_REQUESTS_PER_MINUTE` limits public GETs by a short-lived, HMAC-derived client-address bucket.
  Outside local development, the secret manager must supply `ADMISSION_SCOPE_HMAC_KEY`.
  The API never stores raw addresses.
  `SSE_RECONNECTS_PER_MINUTE` independently limits authenticated cursor reconnects per user.
- Set `ADMISSION_TRUSTED_PROXY_CIDRS` only to direct, trusted ingress proxies that overwrite `X-Forwarded-For`.
  Otherwise, the API uses the direct connection address and ignores forwarded headers.
- `RUNTIME_API_MAX_REQUEST_BYTES` and `RUNTIME_API_MAX_RESPONSE_BYTES` bound both sides of worker communication.
  `RUNTIME_WORKER_TOKEN` is current.
  Operators may configure one old token and an explicit expiry on the API during a coordinated rotation.

`/internal/v1/metrics` is disabled unless `OPERATOR_DIAGNOSTICS_ENABLED=true` and `OPERATOR_DIAGNOSTICS_SUBJECTS` contains the authenticated operator's verified subject.
It emits bounded aggregate counters and timing summaries only: no user IDs, project IDs, model/provider IDs, prompts, credentials, event payloads, or runtime bindings.
Keep this endpoint on an internal/operator-only network policy.
Scrape it independently from public API traffic.

`GET /internal/v1/ops/runs/<opaque-run-id>` uses the same operator gate and records a redacted access audit.
It returns lifecycle, aggregate usage, capability state, and normalized failure information, never prompts, event payloads, provider/model identifiers, runtime references, credentials, or worker identifiers.
PostgreSQL stores run/provider/lease lifecycle series as fixed, content-free aggregates.
The API scrape can therefore observe a separate built-in worker process.

Run, proposal, SSE, authorization, provider-failure, lease-recovery, usage, latency, and readiness metrics support deployment verification.
Staging still requires these checks:

- Real PostgreSQL concurrency and load, including lock contention.
- Worker/provider smoke test.
- Dashboard and alert integration.
- Backup restore drill.
- Operator access-policy test.
