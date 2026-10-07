---
name: polycolab-repository
description: Inspect, modify, and verify the Polycolab repository using its component boundaries, documentation, and tooling. Use for repository development and review, not external-agent research tasks through the service API.
---

# Work in the Polycolab repository

Use this skill for changes and reviews in this pnpm monorepo.
It contains a Svelte application, a generated TypeScript API client, a FastAPI application, and private Python workers.
Run repository commands from the repository root.
Resolve the links below relative to this file.

## Find the relevant context

Check the working-tree diff before editing.
Preserve existing work.
Read the relevant source, nearby tests, and [documentation index](../../../docs/README.md).
Use the [repository map](../../../README.md#repository-map) to locate components.

Product requirements describe intended behavior.
Architecture documents describe the current implementation, with source code resolving discrepancies.
The [roadmap](../../../docs/roadmap.md) records unfinished capabilities.
Scoped agent contributions and optional proposal review exist.
Production Lean/Python runners and native hosted-agent acceptance remain unfinished.

## Choose the component

| Area                 | Source and boundary                                                                                              |
| -------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Browser              | `web/src/` owns the Svelte application. API and authentication adapters live in `lib/`.                          |
| HTTP handlers        | `backend/polycolab/<capability>/routes/` owns capability routes. Shared business policy belongs in services.     |
| Application data     | `backend/polycolab/entities/` owns application data classes and shared enums.                                    |
| Persistence          | `backend/polycolab/db/models/` owns SQLAlchemy mappings. Persistence interfaces live beside capability services. |
| Database migrations  | `backend/polycolab/db/migrations/postgresql/versions/` owns PostgreSQL Alembic migrations.                       |
| Browser API contract | `packages/api-client/` owns the OpenAPI snapshot, generated types, and typed client.                             |

For browser changes, reuse existing components and styles.
Inspect route handling to distinguish service-backed pages, fictional example pages, and test-only routes.
Use the API client through browser adapters rather than duplicating contracts.

For persistence changes, follow the [persistence boundaries](../../../docs/architecture/persistence.md).
The shared transaction interface is `transaction.py`.
Keep Pydantic HTTP schemas within their capability.
Every SQLAlchemy mapped class, including query projections, uses the `Sql` prefix in declarations, imports, and exports.
Application entities, shared enums, unmapped `Base`, and plain table variables do not use that prefix.
Apply schema changes through Alembic migrations.

## Preserve product boundaries

FastAPI owns authorization and canonical PostgreSQL state.
Private workers use authenticated APIs and have no database credential.
Keep immutable research revisions, references to exact revisions, and attributable provenance.
Protect private research and agent conversations from public views.

Authorized agents can save scoped contributions directly.
Public catalogue admission and publication of private research remain human actions.
Consult the [requirements](../../../docs/requirements/README.md) before changing authority or publication behavior.

FastAPI serves the built browser application and APIs in production.
Public and member research routes share the JavaScript application.
Vite serves local development separately.
Consult the [technical contracts](../../../docs/architecture/README.md#technical-contracts) when changing these boundaries.

## Use repository tooling

Use pnpm for JavaScript/TypeScript and uv for Python.
Honor versions in `package.json` and `backend/pyproject.toml`.
Preserve their lockfiles.

Install locked dependencies when needed:

```sh
pnpm install --frozen-lockfile
uv --directory backend sync --all-groups --frozen
```

| Task                                    | Command or guide                              |
| --------------------------------------- | --------------------------------------------- |
| Start the local application             | `pnpm run dev:local`                          |
| Start the Docker stack                  | `pnpm run dev:docker`                         |
| Start Vite separately                   | `pnpm run web:dev`                            |
| Start the API separately                | `pnpm run api:dev`                            |
| Start the private worker                | `pnpm run api:worker`                         |
| Upgrade the configured database         | `pnpm run api:migrate`                        |
| Configure authentication and deployment | [Deployment guide](../../../deploy/README.md) |

FastAPI produces `packages/api-client/openapi.json`.
That snapshot generates `packages/api-client/src/generated/`.
Do not edit either output by hand.
Run `pnpm run api:contract` after intentional API changes.

## Verify changes

Choose checks for the changed area.
Use nearby tests during iteration and relevant broader checks before handoff.
Add regression coverage at the layer that owns changed behavior.

| Area                     | Check                                                                   |
| ------------------------ | ----------------------------------------------------------------------- |
| JavaScript/TypeScript    | `pnpm run check`: formatting, linting, type checking, and tests.        |
| Python                   | `pnpm run api:check`: formatting, linting, typing, and tests.           |
| API contract             | `pnpm run api:contract:check`: snapshot and generated-client freshness. |
| Browser with mocked APIs | `pnpm run test:e2e`. Tests live in `tests/web/browser/`.                |
| Real services            | Follow the [system test guide](../../../tests/system/README.md).        |
| Documentation            | Check formatting and relative links.                                    |

Web unit and component tests live in `tests/web/unit/`.
Backend tests live in `tests/backend/`.
Use [GitHub CI](../../../.github/workflows/ci.yml) to identify CI checks.
Report what changed, relevant checks, and checks that could not run.
Distinguish mocked results, local integration evidence, and deployment verification.

## Maintain documentation

Update affected documentation when behavior or contracts change.
Keep `docs/architecture/` flat and limited to implemented behavior.
Record unfinished work in the roadmap and proposed designs in issues.
Keep agent trackers, handoffs, session transcripts, and dated test logs outside maintained documentation.
Keep credentials, local settings, caches, and build/test artifacts out of commits and diagnostic output.
