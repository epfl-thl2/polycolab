# Local integrated acceptance harness

## Research and external agents (no hosted worker)

```sh
uv run --directory backend python ../tests/system/run_research.py
POLYCOLAB_RESEARCH_BROWSER=1 uv run --directory backend python ../tests/system/run_research.py
POLYCOLAB_RESEARCH_ENCRYPTED_DB_DRILL=1 uv run --directory backend python ../tests/system/run_research.py
```

This separate harness creates a unique disposable Compose project with PostgreSQL 18 and Garage, applies migrations and starts the real FastAPI service on loopback.
It bootstraps a real local account and invokes `polycolab.external_client` in a separate process receiving only the service URL and delegated credential.
No worker/provider/controller is started.
It verifies public committed evidence, scenario replay, relation/comment writes, staged-byte denial, bad digest rejection, conflicting retries, stale edits and revocation.
It also runs PostgreSQL authority cases for expiry, membership loss, cross-workspace denial, visibility changes (including artifact bytes), and private-only search.
Migration cases check preservation of existing public/private research across the unification migration.

The API supports public and private workspaces under the same configuration.
The orchestrator injects corruption and missing bytes into one exact artifact created by the test and verifies public downloads fail closed with 503.
It restores the original bytes and verifies successful reread before any backup capture.
Database/storage credentials are confined to the orchestrator, not the client.

The optional browser gate builds the actual Svelte production bundle, serves it from FastAPI, and runs Chromium against that same PostgreSQL/Garage service.
A real local account creates a public workspace and reveals a one-time credential.
A separate credential-only HTTP context saves attributable research versions, a relationship, a comment and committed evidence, and receives 401 after human revocation.
A fresh anonymous browser context still reads the exact research, comment and evidence bytes afterward.
No API response is mocked.

This credential-bearing browser gate explicitly disables traces and places any failure artifacts in a private temporary directory removed when the harness exits.
Do not enable persistent traces or publish DOM snapshots of the one-time secret.

The optional drill requires real `age`/`age-keygen`.
It stops only its API/Garage and encrypts an actual pg_dump and both cold Garage directories.
It restores a second isolated database and a separate Garage service with separate volumes.
The snapshot deliberately contains an active browser session and external credential.
Before restored API startup, the confirmation-gated global invalidation command revokes the full cohort.
The API then verifies anonymous artifact digests and 401 for the snapshot credential.

It also compares public object listings, complete fixture version histories, exact version reads, relationship lists, and attachment lists before and after recovery.
The fixture requires multiple versions and both directed and bidirectional declarations.
It fails if a collection exceeds the captured fixture bounds rather than silently comparing only a first page.

This uses local key configuration, not an external production key-service restore.
Ephemeral key/plaintext files are in a private temporary directory removed after the test.
The harness removes only its own unique containers/volumes and API child, never unrelated services.

These modes test separate-client integration and the production browser bundle with deterministic inputs.
They do not establish live model reasoning, target-deployment acceptance, or researcher validation.

## Isolated key-service recovery

The separate key recovery gate is:

```sh
uv run --directory backend python ../tests/system/run_key_restore.py
```

The gate performs this sequence:

1. Create two uniquely named disposable OpenBao 2.6.1 instances with a pinned image digest.
2. Initialize and unseal only test state.
3. Create a non-exportable derived Transit key.
4. Wrap a random key under versions 1 and 2.
5. Encrypt a cold snapshot with real age.
6. Restore into a second volume.
7. Unseal the restored instance.
8. Verify both exact versions through the application adapter.

Keys/tokens/shares are never printed and test resources are removed.
No plaintext Transit backup is enabled.
This is a loopback-HTTP, file-backend fixture, not production TLS, Raft/HA, token-renewal or operator custody acceptance.
File storage is deprecated in [OpenBao 2.6](https://openbao.org/community/release-notes/2-6-0/).
Do not copy this fixture into the production profile.
The separately protected Shamir share is held in memory during the drill, not included in the encrypted state archive.

## Optional hosted-worker harness

Run `tests/system/run-local.sh` from the repository root (or execute the path directly).
It starts a disposable PostgreSQL 18 container, runs Alembic, and launches a test-only FastAPI entrypoint, deterministic OpenAI-compatible provider, private built-in worker, and Vite development server.
The Playwright spec calls the real API and worker.
Browser fixtures add a test bearer while responses still come from FastAPI through the production Svelte routes.

Playwright arguments can be passed through for a bounded focused run, for example `tests/system/run-local.sh --grep "SSE|PostgreSQL"`.
Browser scenarios use production Svelte routes.
The former acceptance-only routes are retired.

The built-in registration journey is opt-in and keeps the normal harness closed by default.
It performs this sequence with a fresh database:

1. Bootstrap the fixed administrator.
2. Sign in.
3. Sign out.
4. Register an ordinary account through the exact browser contract.
5. Verify that the account is non-admin.
6. Sign out.
7. Sign in again.

Run the journey:

```sh
POLYCOLAB_INTEGRATION_POSTGRES_PORT=55436 \
POLYCOLAB_INTEGRATION_REGISTRATION_MODE=open \
POLYCOLAB_INTEGRATION_REGISTRATION=1 \
tests/system/run-local.sh --grep "built-in open registration"
```

For the focused M1 journey, run `POLYCOLAB_INTEGRATION_POSTGRES_PORT=55433 tests/system/run-local.sh --grep "M1 real worker"`.
It admits a human statement, creates an exact private reference, completes a private-context agent turn, then authorizes a public direct-write turn in the same session.
The actual API-backed worker saves an attributable failed attempt.
The test inspects deterministic-provider requests and public JSON for private content/IDs.
It reads the result in the production Svelte component through Vite.
It also checks server-rendered HTML with JavaScript disabled.

It is not a production bundle or live-provider test.
Catalogue and scoped direct writes are standard features.
The test-only API entrypoint enables hosted execution for this harness.

The test-only API entrypoint is outside `backend` and cannot be selected by application configuration.
Its `MappingIdentityVerifier` accepts only the fixed `owner`, `contributor`, `reader`, and `outsider` tokens.
Its provider transport forwards a policy-validated provider request to the local fake server.
Do not use either artifact outside this harness.

The scenarios cover these boundaries:

- Private project and exact pinned source revision.
- Researcher run with scoped `get_context` and `submit_proposal` calls.
- Atomic accept/edit/reject review and accepted private canonical results.
- Rejection of whole-project publication and anonymous reads.
  They also exercise these cases:

- Eight concurrent SSE replays.
- Eight concurrent revision writers.
  One wins, and stale writers receive conflicts.
- Membership revocation during reconnect.
- Provider failure normalization.
- Real PostgreSQL stop/start recovery with a durable worker run after readiness returns.

Existing API unit tests retain the focused authorization, replay, stale, SSE, lease-recovery, provider-fault, and database-failure matrices.
This harness is their real process-boundary complement.

The harness destroys only its named disposable Docker volume on exit.
The Vite process uses a strict port and is awaited during cleanup, so a quick rerun cannot silently select another browser origin.
Docker, a compatible `uv` environment, Node dependencies, and Playwright browsers are prerequisites.
It does not represent staging validation, backup restore, deployed network-role isolation, or live provider verification.

## Docker-free development smoke test

Run `uv run --directory backend python ../tests/system/run_local_mode.py` after installing the normal locked dependencies and Playwright Chromium.
It starts a real API and Vite on unused loopback ports with temporary migrated SQLite and filesystem storage.
It exercises registration, research, Library copying, activity and uploads without mocking HTTP or changing the user's local database or Docker services.
The runner stops its process groups and removes its temporary data on exit.
Persistent restart, migration backup/rollback and storage integrity are additionally covered by `tests/backend/test_local_development.py`.
