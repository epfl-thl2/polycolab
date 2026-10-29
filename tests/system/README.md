# Local integrated acceptance harness

## Isolated key-service recovery

The separate key recovery gate is:

```sh
uv run --directory src/backend python ../../tests/system/run_key_restore.py
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

The test-only API entrypoint is outside `src/backend` and cannot be selected by application configuration.
Its `MappingIdentityVerifier` accepts only the fixed `owner`, `contributor`, `reader`, and `outsider` tokens.
Its provider transport forwards a policy-validated provider request to the local fake server.
Do not use either artifact outside this harness.

The retained scenarios cover registration, provider failure normalization, concurrent SSE replays, membership revocation, and PostgreSQL stop/start recovery. The deterministic provider reads authorized workspace context and returns a response.

Existing API unit tests retain the focused authorization, replay, stale, SSE, lease-recovery, provider-fault, and database-failure matrices.
This harness is their real process-boundary complement.

The harness destroys only its named disposable Docker volume on exit.
The Vite process uses a strict port and is awaited during cleanup, so a quick rerun cannot silently select another browser origin.
Docker, a compatible `uv` environment, Node dependencies, and Playwright browsers are prerequisites.
It does not represent staging validation, backup restore, deployed network-role isolation, or live provider verification.

## Docker-free development smoke test

Run `uv run --directory src/backend python ../../tests/system/run_local_mode.py` after installing the normal locked dependencies and Playwright Chromium.
It starts a real API and Vite on unused loopback ports with temporary migrated SQLite and filesystem storage.
It exercises registration, Default file editing, agent-key revocation, private project uploads, Git worktrees, and Linear coediting without mocking HTTP or changing the user's local database or Docker services.
The runner stops its process groups and removes its temporary data on exit.
Persistent restart, migration backup/rollback and storage integrity are additionally covered by `tests/backend/test_local_development.py` and `tests/backend/test_workspace_only_migration.py`.

## Native Docker/gVisor browser gate

`run_hosted.py` creates unique disposable PostgreSQL/Garage services and serves the
compiled browser from a test-only core. A native executor on an idle SSH host
connects through a loopback reverse tunnel. Only model Responses are deterministic;
core authorization, persistence, controller, Codex and Docker/runsc are real.

```sh
POLYCOLAB_GVISOR_SSH_HOST=YOUR_TEST_ALIAS \
POLYCOLAB_GVISOR_REMOTE_SOURCE=/absolute/disposable/source \
  uv run --directory src/backend python ../../tests/system/run_hosted.py
```

The remote source must contain matching backend code, its locked `.venv`, and
`controller.toml` with the accepted gVisor image and prepared finite slots. No
controller may already use that state directory. The runner uses one slot and
creates its own temporary runtime token; it does not use a deployed application's
credential. Port 55073 on the remote loopback interface must be free, or set
`POLYCOLAB_GVISOR_REMOTE_PORT`. SSH must permit reverse forwarding.

The fixture initializes the project's Main worktree before creating its first
conversation. This gate does not cover concurrent first-time worktree initialization
and chat creation on a new project.
The browser sends a chat, exercises a scoped workspace context read and sandbox command,
checks a saved project file, downloads a declared artifact from Garage, reloads
history and sends a follow-up.
Set `POLYCOLAB_HOSTED_DEV=1` to use an isolated Vite frontend for integration
debugging. The default builds and serves production assets; a Vite result does
not establish production-build acceptance.
The runner stops its controller and removes only its own Compose project and
volumes. It retains private synthetic diagnostics on failure. This gate does not
establish live provider behavior, full resource-exhaustion coverage or production
readiness.

## LaTeX compilation

Build the pinned compiler image using the [compiler guide](../../deploy/latex/README.md),
then run:

```sh
POLYCOLAB_LATEX_IMAGE=sha256:<image-id> uv run --directory src/backend python ../../tests/system/run_latex.py
```

The runner creates disposable PostgreSQL/Garage services, starts FastAPI, Vite,
and the private compiler controller, and exercises a real browser compilation.
It verifies a rendered PDF, private access, save-before-compile without a Git
commit, reload persistence, failure diagnostics, retained PDFs, and cancellation.
The worker has no database/storage environment and the compiler has no service
credential. All test services and data are removed afterward. Hosted isolation
and recovery acceptance still require the target daemon.
