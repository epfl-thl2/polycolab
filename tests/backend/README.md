# Backend tests

Run from the repository root:

```sh
pnpm run api:test
pnpm run api:check
```

`api:test` runs pytest. `api:check` also checks formatting, lint, and types.
Tests that require PostgreSQL skip unless their database configuration is supplied.
Use the [system test guide](../system/README.md) for disposable real-service harnesses.

## Shared fixtures

Pytest discovers fixtures in `conftest.py`; request them as test arguments.
Do not import fixtures from other test modules.

- `identity_verifier` provides independent test identities without an application or database.
  Request it directly when creating an application with custom settings.
- `client` provides a FastAPI test client with a fresh in-memory SQLite database.
- `pg_schema` provides an engine, Alembic configuration, and URL for an isolated PostgreSQL schema.
  Set `M0_POSTGRES_TEST_URL` to a disposable test database to enable it.
  Each test gets its own schema, which is removed at teardown.
  Tests apply the migration revision they need; the fixture does not apply migrations.

Keep mutable application and database state isolated per test.
PostgreSQL tests that construct their own application should request `identity_verifier`
rather than obtaining it through the SQLite `client` fixture.
Shared payload builders belong in helper modules, such as `research_requests.py`.
Keep the action under test and its behavioral assertions in the test itself.
