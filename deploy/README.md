# Deployment guide

Fresh installations apply the complete Alembic chain from `20260905_baseline` to `head`.
Existing post-reset installations also upgrade to `head` without resetting accounts or research.
The unification migration removes only sample installation bookkeeping.
It never changes workspace visibility or deletes tutorial research.

Databases from before the 2026-09-05 prototype reset remain unsupported and must not be stamped as current.
No application command resets data automatically.
See the [schema contract](../docs/architecture/research-schema.md).

This guide describes the existing Compose/API/worker implementation.
Verify the selected services on the target deployment.
For current non-execution incident handling and rollback, use the [active operator procedures](INCIDENTS.md).
Live drills remain deployment gates.

Configure [database pool budgets](DATABASE-POOLS.md) across every API/consumer process and rolling-update surge before increasing replica counts.
Use the [protected telemetry guide](OBSERVABILITY.md) for canonical community backlog metrics and their replica-aggregation and failure semantics.
That guide also covers the opt-in, operator-authenticated community pool exporter over a private Unix socket.
The default consumer command remains listener-free.

`docker/compose.yml` starts PostgreSQL, Garage, a migration job, FastAPI, and the community consumer.
Use `--profile execution` for the private built-in worker.
FastAPI is the production web service and serves the compiled Svelte bundle and JSON API.
Public workspaces, Library, agent keys, artifacts, and scoped direct contributions are standard features with no enable/disable flags.
Local browser development runs Vite separately with `pnpm run web:dev`.
The Compose file deliberately uses local-only credentials and loopback ports.

Staging and production must supply configuration through their deployment secret manager from the matching files in `config/`.
The example URLs are not usable credentials.

The two supported development commands are `pnpm run dev:local` (SQLite plus local files, no Docker) and `pnpm run dev:docker` (PostgreSQL plus Garage).
Both read `deploy/docker/.env`.
Local data stays under `.local/`.
Docker data stays in its named volumes.
These datasets are independent.
See the [root README](../README.md#run-locally-or-with-docker) for setup.

Local Compose uses this file for interpolation and container settings.
Explicit `environment:` entries select internal service addresses and per-process pool budgets.
Worker settings remain an allowlist without database credentials.

Garage defaults are in Compose itself, not a second dotenv file.
Host backend commands also read the shared file.
The local launcher selects SQLite and filesystem storage.
Raw `api:dev` remains available for an explicitly configured PostgreSQL backend.

Production overrides the local environment file and uses injected settings only.
`POLYCOLAB_ENV_FILE` is the required private application file for the production overlay.
It is not a local file selector.
Production preflight requires PostgreSQL and complete S3 storage settings.
Do not print resolved secret-bearing configuration.

```sh
docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

The Docker web build allows up to 4 GiB of Node.js old-space heap.
Give the builder additional memory for other build processes.
The Docker build argument `WEB_BUILD_NODE_OPTIONS` overrides this build-only setting if needed.
If a build fails, inspect the output above the final `failed to solve` line for the actual error (for example, `JavaScript heap out of memory`).

If host port 5432 is occupied, select another loopback port.
The API continues to use PostgreSQL port 5432 on the private Compose network:

```sh
POLYCOLAB_POSTGRES_PORT=55432 docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build
```

The local Compose profile uses the built-in account provider.
Open `http://127.0.0.1:8000` after building the web bundle into the API image, or `http://127.0.0.1:5173` while running Vite locally.
Set a random `BOOTSTRAP_ADMIN_PASSWORD` before the first `docker compose up`.
Compose creates the fixed `admin` account after migrations and before the API starts.
The API stores only password verifiers and opaque session digests in PostgreSQL.
Built-in accounts are the default in every environment: `AUTH_MODE=local` names the built-in provider, not a development-only mode.

Organizations may select `AUTH_MODE=oidc` with a configured issuer, JWKS URL, public browser client ID, and API audience.
Keycloak is optional.
The [optional Keycloak realm reference](keycloak/README.md) supplies exact browser callbacks, S256 PKCE and the API audience, with a separate live acceptance checklist.

For deployed built-in authentication, use same-origin HTTPS (session cookies are Secure outside local development).
Supply `BOOTSTRAP_ADMIN_PASSWORD` from secret management while initializing an empty database.
Subsequent starts leave all accounts and passwords unchanged.
Keep the application-side address and username login limits enabled.
Add aggregate login abuse protection at ingress.

Built-in registration remains closed unless `REGISTRATION_MODE=open` or `invitation` is selected explicitly.
Either enabled mode requires the exact `PUBLIC_APP_ORIGIN`.
Keep the application-side durable address rate limit enabled.
Add an ingress limit for `POST /auth/register`.
Configure `ADMISSION_TRUSTED_PROXY_CIDRS` only for direct trusted proxies so spoofed forwarded addresses cannot select rate buckets.

Invitation mode uses administrator-issued codes returned once for operator-mediated delivery.
It requires no mail service.
Before public exposure:

1. Review the effective `/auth/config`.
2. Verify that administrator bootstrap completed.
3. Test registration over HTTPS.

Changing an example file alone must not be treated as authorization to enable enrollment.

Optional direct Google/GitHub sign-in additionally requires the exact public origin and complete provider credentials from secret management.
Register only `/auth/social/google/callback` and `/auth/social/github/callback` on that origin.
Configure ingress access logs to omit callback query strings or suppress callback entries entirely.
OAuth code/state travel in the query.
The application logger records only the path.
Apply rate limits to social start and callback routes.

Verify this redaction before public exposure.

Built-in authentication does not provide password recovery, MFA, or an account-management UI.
Selecting an authentication mode does not establish deployment security acceptance.
Changing providers does not automatically link identities or transfer memberships.
Local credential-encryption keys remain local-only.
Human authentication supports only `local` and `oidc`.
Anonymous reads omit credentials under either mode.

The read-only Scalar reference is available at `/docs/api` by default in local and staging environments.
Production defaults to disabled.
Set `API_REFERENCE_ACCESS=public` to publish it or `operators` together with `API_REFERENCE_OPERATOR_SUBJECTS` to retain an OIDC-subject allowlist.
The legacy `API_REFERENCE_ENABLED=true` production setting continues to mean operator-only access so upgrades cannot accidentally publish a formerly restricted reference.
Scalar cannot send requests or retain credentials in any access mode.

In Vite development, the reference reads the current worktree's generated `packages/api-client/openapi.json`.
Run `pnpm run api:contract` after changing the API contract.
Application requests still use `POLYCOLAB_API_PROXY_TARGET` (port 8000 by default), so inspecting the new reference does not start or migrate the matching backend.

The dedicated migration service applies the locked Alembic chain before API startup.
Local PostgreSQL is exposed only on loopback, using `POLYCOLAB_POSTGRES_PORT` (default 5432).
Host-run API and migration commands must use that selected port.
Container-to-container traffic always uses 5432.
Staging and production should run migrations as a dedicated deployment job, not in every application replica.

## Local deployment

The Library and workspace imports are always available.
Apply the migration through `20260915_submission_numbers` before running this version.
The migration preserves existing literature and status values.
This migration assigns permanent numbers to existing research activity and initializes the counter for new submissions.

The `/library` route uses catalogue-only search.
`/workspaces?scope=member` opens the member working area.
`/workspaces?scope=public` browses public investigations.
No community consumer or hosted execution service is required for the Library.

Scoped version-2 agent tools require explicit per-run write authority, not a deployment feature switch.
Existing version-1 sessions keep their four-tool contract.
Hosted execution has separate controls and defaults to disabled.
Direct-write authority does not grant permission to start execution services.

The `community` Compose service processes catalogue/research outbox events for private notifications and deterministic progress summaries.
It is an application-owned database consumer, separate from the database-free agent worker.
Outside Compose, run `uv --directory backend run python -m polycolab.community_consumer` with the same application/database environment as the API.
It commits bounded recipient batches, resumes after restart, and performs no model calls.

Moderator assignment requires an explicit JSON list of verified human subjects in `CATALOGUE_OPERATOR_SUBJECTS`.
It defaults to `[]`.
The local Compose service supplies these variables.
See the [catalogue contract](../docs/architecture/catalogue.md) for endpoints and authority.
The Svelte Library supplies discovery, admission, revision history and workspace imports.

Local browser and integration tests do not establish deployment acceptance for the combined web/API image.

`docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build` starts PostgreSQL, Garage, migrations, FastAPI, the community consumer and hosted-run reconciler.
Enable the `execution` profile and matching API capability explicitly to start a private built-in worker.
The worker publishes no port.
It reaches model and tool gateways only at `RUNTIME_INTERNAL_API_URL` on the backend network.
Production deployments expose only the FastAPI service for browser/API traffic and run the worker as a separate private process without a database credential.

## Production deployment

There is one Compose model.
Overlay `docker/compose.production.yml` on `docker/compose.yml` for the standard research configuration, without additional profiles.
Use `config/production.env.example` as the application settings reference.
Store the populated file outside the checkout with mode 0600.
Set `POLYCOLAB_ENV_FILE` to its absolute path.

Supply interpolation settings through a separate private `--env-file`: `POLYCOLAB_IMAGE` (an immutable image digest), `POSTGRES_PASSWORD`, `GARAGE_RPC_SECRET`, `GARAGE_DEFAULT_ACCESS_KEY`, `GARAGE_DEFAULT_SECRET_KEY`, and `RUNTIME_WORKER_TOKEN`.
Storage/database credentials must match the application settings.
`POLYCOLAB_API_PORT` defaults to 8000.

```sh
docker compose --env-file /private/path/compose.env -f deploy/docker/compose.yml -f deploy/docker/compose.production.yml config --quiet
docker compose --env-file /private/path/compose.env -f deploy/docker/compose.yml -f deploy/docker/compose.production.yml up -d
```

The production overlay removes local database ports and application environment defaults, uses the same image for migration and API, and runs `python -m polycolab.deployment_preflight` before migration/startup.
Configure a real origin, key service, storage and operator-managed HTTPS ingress.
Registration defaults closed.
Bootstrap the administrator using the existing private bootstrap password setting.
Before exposing public ingress:

1. Configure `PUBLIC_WORKSPACE_MODERATOR_SUBJECTS`.
2. Run `python -m polycolab.deployment_preflight --live`.

Library moderation retains its separate operator settings.
Checks validate configuration and dependencies, not live ingress security or complete release acceptance.

Hosted workers remain optional and receive no database credential.
Verification controllers retain the separate [execution deployment contract](execution/README.md).
Mail queue delivery has no packaged daemon: SMTP configuration must only be enabled after an operator supplies and verifies delivery.
Execution and mail delivery require their own deployment setup.
No old deployment, volume or database is removed automatically.

## Supporting tools

The standalone [Garage configuration](garage/README.md) provides artifact storage for local integration work.
It uses isolated Compose projects and persistent volumes.
The shared Compose model also uses this definition for application storage.
Its fallback credentials are for local development only.
Production requires explicit values.

- `scripts/backup-postgres.sh` creates a private, unique backup bundle and streams directly into encryption outside local development.
  See the active [recovery contract](RECOVERY.md) for completion markers, connection-secret handling and the remaining coordinated database/artifact/key recovery gates.
- `scripts/restore-postgres.sh` restores only into an explicitly named `polycolab_restore_*` database.
  `scripts/verify-restore.sh` runs the isolated local drill.
  It removes only that exact temporary database after successful verification.
- The staging gate contract is in [`staging/staging-gate.md`](staging/staging-gate.md), with the protected environment workflow in `../.github/workflows/staging-gate.yml`.

Public documentation is built by the uv-locked Zensical project in `docs-site/` using its MkDocs-compatible `mkdocs.yml`.
The existing `pnpm run web:build` and Docker build include it in `web/dist/docs`.
No additional production server is needed.
`pnpm run web:dev` proxies Zensical through the same Vite origin.
Reload after editing a guide.

## Hosted execution recovery in development

Both `pnpm run dev:local` and the canonical `deploy/docker/compose.yml` run the application-owned hosted reconciler.
It keeps expired runs and provider reservations recoverable without requiring a live Linux controller.
The native controller remains separate and opt-in.
Local development does not emulate a VM.
Set hosted image/capacity options in the shared `deploy/docker/.env` only when preparing hosted execution.
See [Linux hosted agents](execution/README.md).

The Docker reconciler uses two database connections with zero overflow.
Production overrides use the same private application environment file as the API.
Applying Docker settings recreates the reconciler along with the API and community consumer.

## Recoverable agent API keys

Apply the current migration before starting the updated API.
Newly issued keys are encrypted using the same configured credential wrapper as model-provider credentials.

For `KMS_PROVIDER=local`, set a persistent `LOCAL_CREDENTIAL_MASTER_KEY` in `deploy/docker/.env` **before issuing keys**.
Generate a 32-byte, base64-encoded key with `openssl rand -base64 32`.
Keep it with your deployment secrets and backups.

Without this setting, the local wrapper is ephemeral and secrets cannot be revealed after an API restart.
Production uses the configured KMS provider.
Retain access to historical wrapping keys.
Existing hash-only agent keys still work but cannot be revealed.

## Persistent workspace files

The API mounts `workspace-repositories` at `/var/lib/polycolab/repositories`.
Set `WORKSPACE_REPOSITORY_DIRECTORY` to this absolute path in the private
production environment file; the production overlay resets local environment
entries. Docker-free development uses `.local/repositories`. Git must be
installed on the API host (the application image includes it).

For a host directory, replace the API volume mapping with
`/absolute/host/workspace-repositories:/var/lib/polycolab/repositories` and grant
the container API user read/write access. Keep it on one host with local POSIX
file locking. Sandboxes receive clones through the API; they never mount this
volume. This initial deployment does not support independent repository volumes
on multiple API hosts.

Apply migrations to `20261006_workspace_files` before serving the new routes.
Browser files can ship first; rebuild and verify the protocol-3 hosted controller
and curated image before enabling agent checkout. See the
[workspace-file contract](../docs/architecture/workspace-files.md) for coordinated
SQL/Git backups, restore checks, quotas, and rollback.
