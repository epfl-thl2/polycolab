# Polycolab

Polycolab is an online project workspace for people and agents. Project files are the shared working material.

The service supports Default server files, Git worktrees, Linear collaboration, project conversations and optional hosted execution, artifacts, LaTeX builds, accounts, memberships, and revocable agent credentials. The independent agent library and direct chat API remain available.

FastAPI serves the compiled Svelte application and APIs in production. Public project metadata is discoverable; files and conversations require their applicable access permissions. Private workers call authenticated APIs without database credentials.

Start with the [documentation index](docs/README.md).
The [architecture](docs/architecture/README.md) describes the current implementation.
Coding agents follow the repository's [agent guidance](AGENTS.md) for development and checks.
For browser test authoring, execution, and debugging, use the [E2E testing skill](.agents/skills/polycolab-e2e/SKILL.md) as `$polycolab-e2e`.

## Common commands

1. Install the JavaScript dependencies from the lockfile:

   ```sh
   pnpm install --frozen-lockfile
   ```

2. Install the Python dependencies from the lockfile:

   ```sh
   uv --directory src/backend sync --all-groups --frozen
   ```

3. Run the repository's JavaScript and TypeScript checks:

   ```sh
   pnpm run check
   ```

## Repository map

| Directory                     | Contents                                                       |
| ----------------------------- | -------------------------------------------------------------- |
| `src/web/`                    | Svelte browser application                                     |
| `src/backend/`                | FastAPI services, database migrations, and private workers     |
| `src/web/src/lib/api-client/` | Generated TypeScript API types and typed client                |
| `src/web/src/styles/`         | Frontend styles and canonical color tokens                     |
| `tests/`                      | Browser, backend, execution, and system checks                 |
| `deploy/`                     | Deployment configuration and operator guides                   |
| `docs/`                       | Product requirements, implementation architecture, and roadmap |
| `docs-site/`                  | Public documentation for users and developers                  |
| `skills/`                     | Instructions for external agents that use Polycolab            |
| `.agents/skills/`             | Skills for coding agents that work on this repository          |

See the [architecture](docs/architecture/README.md) for component boundaries.

## Run locally or with Docker

Install the dependencies with the [common commands](#common-commands).
Create the shared file for local settings:

```sh
cp deploy/docker/.env.example deploy/docker/.env
```

### Run without Docker

1. Start the local services:

   ```sh
   pnpm run dev:local
   ```

2. When you first start the services, choose an administrator password at the prompt.
   You can instead supply `BOOTSTRAP_ADMIN_PASSWORD`.
3. Open **http://localhost:5174**.
4. Use `admin` as your username to access your account.

The command starts these processes:

- Vite.
- The Python API, which reloads after source changes.

The API owns hosted-run recovery, artifact cleanup, and document-build maintenance
as background jobs in the same process.

The local services store accounts and project metadata in `.local/polycolab.db`.
They store uploads in `.local/artifacts/`.
This data persists across restarts.

Before startup, the command applies pending SQLite migrations.
Before an upgrade, it saves a backup of the existing database in `.local/backups/`.
A failed upgrade stops startup.
The workspace-only migration intentionally discards the retired research-object data while preserving workspace data. See the [upgrade notes](deploy/README.md).

Press Ctrl+C to stop all processes that the command starts, or run `pnpm run dev:stop`
from another terminal in the same checkout. Shutdown allows five seconds for graceful
exit before forcing remaining child processes to stop. Local data is preserved.
The control socket uses a private directory under `/tmp`, keyed by the checkout’s
canonical path. Concurrent starts are rejected. If a launcher is forcibly killed
during socket setup, the next start may report a leftover `.lock` directory;
after ensuring no launcher is starting, remove only the directory named in that error.
The stop command controls launches made with this updated launcher; it cannot recover
processes already orphaned by an older launcher.
Restart the command after changes to `deploy/docker/.env`.
Source changes reload automatically.

### Run with Docker

Docker uses `core`, `postgres`, and `object-storage`, with an optional `worker`.
`pnpm run dev:docker` runs migrations in a temporary core container before startup.
For installations using the old service names, follow the
[Compose upgrade procedure](deploy/README.md#upgrade-from-the-previous-service-names)
before starting the new stack.

1. Before the first start, set `BOOTSTRAP_ADMIN_PASSWORD` in `deploy/docker/.env`.
2. Start the Docker services:

   ```sh
   pnpm run dev:docker
   ```

3. Open **http://localhost:8000**.

PostgreSQL and Garage store data in persistent Docker volumes.
They do not share data with the local SQLite mode.
Docker reuses existing `polycolab` volumes.

To apply changed environment settings without an image rebuild, run:

```sh
pnpm run dev:docker:apply
```

To stop the Docker services without data removal, run:

```sh
docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yml down
```

Stop one mode before you start the other.
Both APIs use port 8000.
Neither command silently stops the other mode or changes that mode's data.
Never use `down -v` for routine restarts.

### Shared settings

Both development commands read **`deploy/docker/.env`**.
They do not read `.env` files from the repository root, `src/backend/`, or legacy deployment directories.
Shell variables override values in the file.
Each command selects the database and storage addresses for its mode.

Registration defaults to closed.
Set `REGISTRATION_MODE=open` to permit account creation.

If `PUBLIC_APP_ORIGIN` has no value, each command selects the browser origin for its mode.
The origin identifies the protocol, host, and port in the browser URL.
If you supply `PUBLIC_APP_ORIGIN`, the commands preserve your value.
The value must match the browser URL, including its port.

To use Vite with the Docker API:

1. Set `PUBLIC_APP_ORIGIN` to the Vite browser's origin.
2. Start Vite separately with `pnpm run web:dev`.

Production uses a separate private configuration.
It does not use the development settings file.
See the [deployment guide](deploy/README.md).

Agent execution requires the private worker.
Other application features do not require that worker.
Frontend unit tests and browser tests with mocked APIs do not require Docker or authentication.

## License

Polycolab's original source code and repository documentation use the [Apache License 2.0](LICENSE).
Third-party code retains its existing licenses and attribution notices.
See the [third-party notices](ThirdPartyNotices.txt).
