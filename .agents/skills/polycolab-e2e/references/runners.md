# E2E runners

All commands run from the repository root.
The configurations and runner source are authoritative for flags, ports, and test selection.

## Prerequisites

Use the locked dependencies and tool versions described in [AGENTS.md](../../../../AGENTS.md).
Install Chromium when it is missing:

```sh
pnpm --filter @polycolab/web exec playwright install chromium
```

Real-service runners also need the locked backend environment.
The PostgreSQL runners require Docker.

## Mocked browser suite

The [browser configuration](../../../../tests/web/browser/playwright.config.ts) starts Vite and retains traces on failure.
Run the full suite with `pnpm run test:e2e`, or select a spec:

```sh
pnpm --filter @polycolab/web exec playwright test --config ../../tests/web/browser/playwright.config.ts research-workflow.spec.ts --workers=1
```

Use `--grep` to select a named journey and `--list` to check discovery without running it.
Set `E2E_PORT` to an unused port when 5173 is occupied.
`E2E_BASE_URL` disables server startup; use it only for an intentionally selected compatible test server.
This suite uses mocked APIs even if the supplied URL points to real services.

## Compiled browser with mocked APIs

Build the browser before running the [production-preview configuration](../../../../tests/web/browser/playwright.production.config.ts):

```sh
pnpm --filter @polycolab/web run build
pnpm --filter @polycolab/web exec playwright test --config ../../tests/web/browser/playwright.production.config.ts
```

The configuration starts Vite preview on port 4183 and selects an explicit subset of specs.
This checks compiled browser behavior with mocked responses.
CI separately runs `pnpm run web:build`, which also builds the documentation site.

## Real local-mode smoke test

```sh
uv run --directory src/backend python ../../tests/system/run_local_mode.py
```

The [runner](../../../../tests/system/run_local_mode.py) starts FastAPI and Vite on unused loopback ports with temporary migrated SQLite and filesystem artifacts.
It runs `tests/web/browser/local/service.spec.ts` and removes its temporary data and child services afterward.
It establishes local-mode integration; PostgreSQL locking and production storage require their own gates.

## Real research browser gate

```sh
POLYCOLAB_RESEARCH_BROWSER=1 uv run --directory src/backend python ../../tests/system/run_research.py
```

The [runner](../../../../tests/system/run_research.py) creates a unique disposable PostgreSQL/Garage Compose project, migrates the database, and serves the built Svelte application from FastAPI.
It runs real external-client and authority checks plus `tests/system/specs/public-agent-real-service.spec.ts`.
Use this gate for public research, delegated contributions, evidence bytes, and revocation across real process boundaries.
No hosted worker or live model provider runs.
Keep its trace disabling and private temporary failure-artifact handling intact because the browser reveals a one-time credential.
The browser spec is gated by runner-provided environment; invoking that spec alone can skip the journey.

## Real hosted-worker journeys

```sh
tests/system/run-local.sh --grep "M1 real worker"
```

The [runner](../../../../tests/system/run-local.sh) builds the browser, then starts PostgreSQL, a test-only API, a deterministic provider, the private worker, and Vite.
It passes Playwright arguments through to `tests/system/playwright.config.ts`; choose the spec or `--grep` relevant to the task.
Authenticated browser journeys use Vite; some anonymous checks read compiled assets directly from FastAPI.
The harness uses fixed API/provider/Vite ports and a fixed Compose project. Run one instance at a time and let its cleanup finish before rerunning.
Changing URL environment variables alone does not relocate those process listening ports.
See the [system guide](../../../../tests/system/README.md#optional-hosted-worker-harness) for opt-in registration and other gates.
Results establish real worker integration with deterministic provider inputs; native hosted-agent isolation, live reasoning, and target-deployment acceptance remain separate checks.
