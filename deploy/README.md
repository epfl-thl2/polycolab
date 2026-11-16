# Deployment guide

Fresh installations apply the complete Alembic chain. Existing installations upgrade to `head` using forward migrations.

The research helper uses a shared platform-managed model. Set `RESEARCH_HELPER_API_KEY` through the server environment or secret store, and set `RESEARCH_HELPER_BASE_URL` (an HTTPS API base URL) and `RESEARCH_HELPER_MODEL` (the model ID). `RESEARCH_HELPER_WIRE_API` defaults to `chat_completions`; use `responses` for Responses endpoints. No personal provider connections are used. The helper remains unavailable until all three required settings are present. `FEATURE_RESEARCH_HELPER_ENABLED` defaults to `true`; set it to `false` to disable the helper even when configured. `RESEARCH_HELPER_REQUESTS_PER_MINUTE` defaults to 5 per user, and `RESEARCH_HELPER_GLOBAL_REQUESTS_PER_MINUTE` defaults to 30 across users and API processes. No project or private worker is required.

Apply the `20261115_research_helper` migration (or its `local_` SQLite counterpart) before enabling helper requests. It adds admission-counter scopes while preserving existing counters. Restart `dev:local` to back up and migrate an existing local database. Chat text is held only in the browser's current homepage session and is not saved to conversation history. Provider inference is charged to the platform credential.

The key terminology migration renames `external_agent_credentials` to
`agent_api_keys`, its ownership field to `owner_user_id`, and its write counters to
`write_count` and `max_writes`. The API uses those same names and reports
`writes_remaining`. Execution requests use `requested_by_user_id`. Key bytes,
expiry, permissions, and counting rules are unchanged. Configure
`AGENT_API_KEY_TTL_SECONDS`, `AGENT_API_KEY_MAX_REQUESTS`, and
`AGENT_API_KEY_MAX_WRITES` instead of the former `EXTERNAL_AGENT_*` settings.
Upgrade API and browser together; previous field names are not API aliases.

The provider-connection migration renames `provider_profiles` to
`provider_connections` and updates run, grant, audit, and legacy-history references.
Clients must use `/api/v1/account/provider-connections` and
`provider_connection_id`; the old provider-profile routes are removed. Provider
credential ciphertext and authenticated encryption contexts remain unchanged.

Project roles now use `OWNER`, `EDITOR`, and `VIEWER`. The role migration converts
existing memberships and invitations from `CONTRIBUTOR` and `READ_ONLY` while
preserving their permissions. Clients must send the new values; the previous
role names are rejected.

Saved conversations now use `/api/v1/conversations`, `conversation_id`, and
`child_conversations`. Repository bindings use `/repository/conversations`.
Conversation sharing values are `private`, `members_can_view`, and
`members_can_participate`. Database migrations preserve transcript/run IDs and
runtime bindings while renaming their conversation references. Authentication
sessions and harness runtime sessions remain separate concepts. Git branch names
and immutable event payloads retain their original bytes.

Deploy worker protocol 7 with this API. Drain work and stop writers before the
cutover; older worker protocols cannot claim work. Browser locations use
`/projects/{id}/conversations` and `/settings/conversation-history`. Superseded
workspace, session, Connections, and provider-settings paths show not found;
they do not redirect. Update bookmarks and API clients with the application.

Run these terminology migrations online against the stopped application’s database. They inspect and preserve existing constraints and trigger definitions; offline `alembic upgrade --sql` is rejected rather than emitting an incomplete upgrade.

The same cutover renames `projects.workspace_mode` to `file_mode`, mapping `default` to `basic` and `linear` to `collaborative`. File APIs use `/collaborative`, and grouped agent edits use `/collaborative/change-sets`. Existing `.linear` directories, checkpoint Git refs, operation payloads, digests, and `batch:` retry keys retain their storage identities.

Library routes move to `/library` in the browser and `/api/v1/library` in the API. The private view is My library (`/mine`); library resources use `item` and `item_id`. Rename `AGENT_LIBRARY_MODERATOR_SUBJECTS` to `LIBRARY_MODERATOR_SUBJECTS` in deployment settings. Published content and existing retry digests are preserved.

Internal tables now use `execution_jobs`, `idempotency_records`, and `repository_idempotency_records`. Scheduling records use `scope_kind` and `scope_id`. Hosted model requests use `reconcile_by` and `reconciled_at`; update monitoring queries to `polycolab_hosted_reconciliation_total`. The upgrade retains existing aggregate counts, retry digests, and scheduling history.

The account/worktree migrations retire external-agent identities, rename `project_tasks`
to `worktrees`, and rename `gateway_profiles` to `provider_connections`. Existing key
secrets and limits, provider credential envelopes, working-copy IDs, and Git branches
are preserved. Deploy the matching API, browser, and workers together: the old
`/api/v1/account/agents`, project `/tasks`, `/api/v1/gateway/profiles`, and
`/api/v1/users/me` endpoints are removed. Clients must use the worktree endpoints,
`/api/v1/account/provider-connections`, and `/api/v1/account`, with `worktree_id` and
`provider_connection_id` in conversation requests. Key creation accepts a name without an
`agent_id`. Apply both database and application updates before reopening traffic;
rollback requires the matching pre-upgrade backup and application version.

The `20261029_workspace_only` PostgreSQL revision and matching SQLite revision permanently remove research objects, revisions, relationships, catalogue/commons/publication data, proposals, verification jobs, research history, and notifications. Development research data is intentionally discarded. Accounts, projects, memberships, credentials and usage counts, conversations, workspace files, library content, and project artifacts are retained. Commons-only artifact bytes are queued for ordinary garbage collection.

Stop old API/worker processes before migration and start the new binaries afterward. Existing tool capabilities are revoked. Nonterminal agent runs with retired research grants are cancelled before those grants are removed, with a recorded cancellation reason and invalidated worker leases. They must not be resumed automatically using private conversation context. Take the normal database/files/artifacts backup first; downgrade requires restoring it. Do not stamp an old database or reset the migration chain. SQLite's upgrade runner creates its normal pre-upgrade backup.

If this revision was already applied before the cancellation safeguard was added, Alembic will not rerun it. Keep workers stopped and inspect outstanding pre-upgrade runs before restarting execution: their deleted grants can no longer establish the original context restrictions. The safeguard does not undo model input already sent before the fix.

This guide describes the existing Compose/API/worker implementation.
Verify the selected services on the target deployment.
For current non-execution incident handling and rollback, use the [active operator procedures](INCIDENTS.md).
Live drills remain deployment gates.

Configure [database pool budgets](DATABASE-POOLS.md) across every API/consumer process and rolling-update surge before increasing replica counts.
Use the [protected telemetry guide](OBSERVABILITY.md) for API pool metrics.

`docker/compose.yml` defines `postgres`, `object-storage` (Garage), and `core`
(FastAPI, the browser application, and background jobs).
The deployment launcher runs migrations in a temporary core container before starting core.
Use `--profile execution` for the private built-in worker.
FastAPI is the production web service and serves the compiled Svelte bundle and JSON API.
Projects, files, agent API keys, and artifacts are standard features with no enable/disable flags.
Local browser development runs Vite separately with `pnpm run web:dev`.
The Compose file deliberately uses local-only credentials and loopback ports.

Staging and production must supply configuration through their deployment secret manager from the matching files in `config/`.
The example URLs are not usable credentials.

The two supported development commands are `pnpm run dev:local` (SQLite plus local files, no Docker) and `pnpm run dev:docker` (PostgreSQL plus Garage).
Both read `deploy/docker/.env`.
For simultaneous worktrees, `dev:local` automatically chooses free ports when defaults are occupied. To pin ports, pass distinct `--web-port`, `--api-port`, and `--collaboration-port` values to `dev:local`; use `--public-origin` when the browser address differs (for example, an SSH tunnel). See the [local setup examples](../README.md#run-without-docker).
Use `pnpm run dev:status` to see the current worktree’s browser address, service URLs, and live health. Startup prints `Ready` only after all three services respond successfully; failed startup health checks time out after two minutes and stop the services.
Stop local mode with Ctrl+C or `pnpm run dev:stop` from the same checkout.
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
bash deploy/scripts/deploy-stack.sh build --env-file deploy/docker/.env -f deploy/docker/compose.yml
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
POLYCOLAB_POSTGRES_PORT=55432 bash deploy/scripts/deploy-stack.sh build --env-file deploy/docker/.env -f deploy/docker/compose.yml
```

The local Compose profile uses the built-in account provider.
Open `http://127.0.0.1:8000` after building the web bundle into the API image, or `http://127.0.0.1:5173` while running Vite locally.
Set a random `BOOTSTRAP_ADMIN_PASSWORD` before the first deployment.
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

In Vite development, the reference reads the current worktree's generated `src/web/openapi.json`.
Run `pnpm run api:contract` after changing the API contract.
Application requests still use `POLYCOLAB_API_PROXY_TARGET` (port 8000 by default), so inspecting the new reference does not start or migrate the matching backend.

The deployment launcher waits for PostgreSQL and object storage, then applies the
locked Alembic chain through `docker compose run --rm --no-deps -T core python -m polycolab.operations.migrate`.
Migration failure leaves core stopped; the temporary container is removed.
Use the launcher for startup and upgrades: plain `docker compose up` does not run migrations.
Local PostgreSQL is exposed only on loopback, using `POLYCOLAB_POSTGRES_PORT` (default 5432).
Host-run API and migration commands must use that selected port.
Container-to-container traffic always uses 5432.
Production runs the same temporary job with configuration preflight before Alembic.

## Local deployment

Project files, membership, keys, and artifacts are core functionality. Hosted execution remains optional. Core runs hosted recovery, artifact cleanup, and document-build maintenance in background jobs sharing the application pool. Run one application process on one host; independent replicas are outside this deployment model.

The launcher starts PostgreSQL, Garage, migrations, and FastAPI. Enable the `execution` profile and API capability to run a private built-in worker. The worker publishes no port and has no database credential. Local tests do not establish target-deployment acceptance.

## Production deployment

There is one Compose model.
Overlay `docker/compose.production.yml` on `docker/compose.yml` for the standard workspace configuration, without additional profiles.
Use `config/production.env.example` as the application settings reference.
Store the populated file outside the checkout with mode 0600.
Set `POLYCOLAB_ENV_FILE` to its absolute path.

Supply interpolation settings through a separate private `--env-file`: `POLYCOLAB_IMAGE` (an immutable image digest), `POSTGRES_PASSWORD`, `GARAGE_RPC_SECRET`, `GARAGE_DEFAULT_ACCESS_KEY`, `GARAGE_DEFAULT_SECRET_KEY`, and `RUNTIME_WORKER_TOKEN`.
Storage/database credentials must match the application settings.
`POLYCOLAB_API_PORT` defaults to 8000.

```sh
docker compose --env-file /private/path/compose.env -f deploy/docker/compose.yml -f deploy/docker/compose.production.yml config --quiet
bash deploy/scripts/deploy-stack.sh pull --env-file /private/path/compose.env -f deploy/docker/compose.yml -f deploy/docker/compose.production.yml
```

The production overlay removes local database ports and application environment defaults, uses the core image for both migration and application startup, and runs `python -m polycolab.deployment_preflight` before migration/startup.
Configure a real origin, key service, storage and operator-managed HTTPS ingress.
Registration defaults closed.
Bootstrap the administrator using the existing private bootstrap password setting.
Before exposing public ingress:

1. Configure `PUBLIC_PROJECT_MODERATOR_SUBJECTS`.
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

Both `pnpm run dev:local` and the canonical `deploy/docker/compose.yml` run hosted reconciliation inside the core application.
It keeps expired runs and provider reservations recoverable without requiring a live Linux controller.
The native controller remains separate and opt-in.
Local development does not emulate a VM.
Set hosted image/capacity options in the shared `deploy/docker/.env` only when preparing hosted execution.
See [Linux hosted agents](execution/README.md).

Background jobs share the API connection budget.
Applying Docker settings recreates the API and its background jobs together.
See the service-renaming upgrade procedure below before applying the new Compose model.

## Recoverable agent API keys

Apply the current migration before starting the updated API.
Newly issued keys are encrypted using the same configured credential wrapper as model-provider credentials.

For `KMS_PROVIDER=local`, set a persistent `LOCAL_CREDENTIAL_MASTER_KEY` in `deploy/docker/.env` **before issuing keys**.
Generate a 32-byte, base64-encoded key with `openssl rand -base64 32`.
Keep it with your deployment secrets and backups.

Without this setting, the local wrapper is ephemeral and secrets cannot be revealed after an API restart.
Production uses the configured KMS provider.
Retain access to historical wrapping keys.
Existing hash-only agent API keys still work but cannot be revealed.

## Persistent project files

Core mounts `workspace-repositories` at `/var/lib/polycolab/repositories`.
Set `PROJECT_REPOSITORY_DIRECTORY` to this absolute path in the private
production environment file; the production overlay resets local environment
entries. Docker-free development uses `.local/repositories`. Git must be
installed on the API host (the application image includes it).

For a host directory, replace the core volume mapping with
`/absolute/host/project-repositories:/var/lib/polycolab/repositories` and grant
the container API user read/write access. Keep it on one host with local POSIX
file locking. Sandboxes receive clones through the API; they never mount this
volume. This initial deployment does not support independent repository volumes
on multiple API hosts.

Apply migrations to `20261006_project_files` before serving the new routes.
Browser files can ship first; rebuild and verify the protocol-3 hosted controller
and curated image before enabling agent checkout. See the
[project-file contract](../docs/architecture/project-files.md) for coordinated
SQL/Git backups, restore checks, quotas, and rollback.

## Upgrade from the previous service names

The launcher refuses legacy `api`, `garage`, `migrate`, `community`, or
`execution-reconciler` containers in the selected Compose project, including stopped
containers. This prevents two Garage instances from opening the same volumes.

1. Drain execution and stop writers, including the old worker and background consumers.
2. Follow the [recovery contract](RECOVERY.md) to capture PostgreSQL, both Garage
   volumes, project repositories, and required key material together. Check the old
   API's mounts before removing it; preserve any container-local project files.
3. Stop and remove only the five legacy service containers listed above. Keep
   PostgreSQL, the worker, and every named volume. Do not use `down -v`, volume
   pruning, or blanket orphan removal. Retain the previous image and configuration
   for rollback.
4. In private settings, change internal S3 URLs from `http://garage:3900` to
   `http://object-storage:3900` and internal application URLs from `http://api:8000`
   to `http://core:8000`. External S3 endpoints and public origins stay as configured.
5. Run the launcher with the same Compose project name and environment files.
   Include `--profile execution` if using the legacy worker; it is stopped before
   migrations and restarted only when selected by the profile.
6. Verify login, existing project files and artifact downloads before reopening writes.

Volume keys remain `postgres-data`, `garage-metadata`, `garage-data`, and
`workspace-repositories`. Ports, bucket/region settings, and existing
`POLYCOLAB_API_*` configuration variables retain their names and meanings.
The standalone Garage and disposable test stacks keep their own service names.

Launcher modes are `build` for local images, `pull` for published production images,
and `reuse` to reapply configuration with existing application images. All modes run
migrations before recreating core. The `pnpm run dev:docker` and
`pnpm run dev:docker:apply` commands select `build` and `reuse`, respectively.
For an upgrade failure, keep writers stopped and follow the recovery contract;
do not automatically downgrade the database.

## Library moderation

Library access does not depend on hosted execution.
Apply the complete Alembic chain through `head` before running the matching application.
Set `LIBRARY_MODERATOR_SUBJECTS` to an explicit JSON list of verified human subjects allowed to hide and restore library items.
It defaults to an empty list.
Use `GET /api/v1/library/{item_id}/moderation` to load the current revision, then POST to that endpoint with the expected revision, hidden state, a reason, and an Idempotency-Key.
Published versions remain immutable; restore a verified backup instead of downgrading away library history.

Projects choose Basic files, Collaborative history, or Git mode. See [Collaborative project operations](../docs/architecture/collaborative-projects.md#operation-and-verification) for the collaboration service, configuration, and coordinated backups.

## LaTeX compiler

Optional project/worktree compilation uses a separate Docker controller. See the
[LaTeX deployment guide](latex/README.md) for image setup, private credentials,
local startup and hosted acceptance.
