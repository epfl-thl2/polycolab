# Agent guidance

Guidance for coding agents working in the Polycolab repository.
Use the [documentation index](docs/README.md) for task-specific context and the [repository map](README.md#repository-map) to find source and tests.
Read the source, tests, and documents relevant to the change.

## Local development shortcuts

Run commands from the repository root.
Use pnpm for JavaScript/TypeScript and uv for Python, with the versions declared in `package.json` and `src/backend/pyproject.toml`.
Install locked dependencies with `pnpm install --frozen-lockfile` and `uv --directory src/backend sync --all-groups --frozen`.

| Task                      | Command                |
| ------------------------- | ---------------------- |
| Start local SQLite mode   | `pnpm run dev:local`   |
| Start the Docker stack    | `pnpm run dev:docker`  |
| Start Vite separately     | `pnpm run web:dev`     |
| Start the API separately  | `pnpm run api:dev`     |
| Start the private worker  | `pnpm run api:worker`  |
| Migrate the configured DB | `pnpm run api:migrate` |

See the [deployment guide](deploy/README.md) for authentication and deployment configuration.

## Component boundaries

- `src/web/src/` owns the Svelte application. Reuse its components and styles, and call the typed API client through adapters in `src/web/src/lib/`.
- `src/backend/polycolab/<capability>/routes/` owns HTTP handlers and capability-local Pydantic schemas. Shared business policy belongs in capability services.
- `src/backend/polycolab/entities/` owns application dataclasses and shared enums; it must not depend on HTTP schemas or database adapters.
- `src/backend/polycolab/db/` owns SQLAlchemy mappings, stores, and converters. Follow the [persistence contract](docs/architecture/persistence.md) for store interfaces and the shared `transaction.py` boundary.
- Every SQLAlchemy mapped class, including query projections, uses the `Sql` prefix in declarations, imports, and exports. Application entities, shared enums, unmapped `Base`, and plain table variables are exempt.
- Apply schema changes through Alembic. Add SQLite revisions alongside PostgreSQL revisions where the shared schema changes; preserve migration/model parity.

## Product and authority boundaries

FastAPI owns authorization and canonical production PostgreSQL state.
Private workers call authenticated APIs and have no database credential.
Preserve immutable research revisions, exact revision references, and attributable provenance.
Keep private research and agent conversations out of public views.

Authorized agents can save contributions within their scopes.
Public catalogue admission and publication of private research are human actions.
Read the [requirements](docs/requirements/README.md) before changing these authority boundaries.

FastAPI serves the built browser application and APIs in production; Vite serves local development separately.
Public and member research routes share the JavaScript application.
Check route handling before treating example pages or test fixtures as service-backed behavior.
See the [technical contracts](docs/architecture/README.md#technical-contracts) when changing these boundaries.

## Generated API contract

FastAPI produces `src/web/openapi.json`, which generates `src/web/src/lib/api-client/generated/`.
Do not edit either output by hand.
Run `pnpm run api:contract` after intentional API changes and verify freshness with `pnpm run api:contract:check`.

## Verify changes

Use focused checks during iteration and the relevant broader checks before handoff.
Place regression coverage at the public boundary that owns the changed behavior.
The [CI workflow](.github/workflows/ci.yml) defines the repository checks.

| Area                  | Check                                                                  |
| --------------------- | ---------------------------------------------------------------------- |
| JavaScript/TypeScript | `pnpm run check`: formatting, linting, type checking, and tests        |
| Python                | `pnpm run api:check`: formatting, linting, typing, and tests           |
| API contract          | `pnpm run api:contract:check`: snapshot and generated-client freshness |
| Browser journeys      | Use the [E2E testing skill](.agents/skills/polycolab-e2e/SKILL.md)     |
| Real services         | Follow the [system test guide](tests/system/README.md)                 |
| Documentation         | Check formatting and relative links                                    |

Web unit/component tests live in `tests/web/unit/`; backend tests live in `tests/backend/`.
For E2E test authoring, execution, or debugging, use `$polycolab-e2e` to select the appropriate browser or real-service harness.

## Documentation and artifacts

Update affected documentation when behavior or contracts change.
Product requirements define intended behavior; architecture documents describe the current implementation, with source code resolving discrepancies about what exists.
Keep `docs/architecture/` flat and limited to implemented behavior.
Record unfinished capabilities in the [roadmap](docs/roadmap.md) and proposed designs in issues.

Keep agent trackers, handoffs, session transcripts, and dated test logs outside maintained documentation.
Keep credentials, local settings, caches, and build/test artifacts out of commits and diagnostic output.
Use comments to explain the scenario or constraint, rather than the history of a change.

## Finishing a task

Report what changed, which relevant checks ran, and any checks that could not run.
Distinguish mocked browser results, real local integration evidence, and verification on the target deployment.
For user-facing changes, give concrete steps and expected behavior so the user can verify the result, including any required setup.
