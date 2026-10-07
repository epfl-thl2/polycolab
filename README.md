# Polycolab

Polycolab is a browser workspace for mathematics and theoretical computer science.
It saves research in immutable versions: each saved version remains unchanged.
The intended service connects a public research commons with private workspaces.
Humans and agents develop versioned statements and Lean/Python evidence.
Humans create public catalogue entries.
Agents contribute within authorized scopes.

The current implementation supports:

- Public and private workspaces.
- Immutable research versions.
- Library admission and imports.
- Agent contributions within authorized scopes.
- Optional proposals for human review.

Production Lean/Python runners remain unfinished.
Acceptance checks for hosted agents in native execution environments also remain unfinished.
See the [roadmap](docs/roadmap.md) for details.

Vite builds the Svelte browser application.
FastAPI serves the compiled application and JSON APIs.
The APIs return only data that anonymous readers have permission to read.
Public research pages and pages for members use the same browser application.
These pages require JavaScript.

Private workers call authenticated APIs.
They have no endpoint for browser access and no database credential.

Start with the [documentation index](docs/README.md).
The [architecture](docs/architecture/README.md) describes the current implementation.
Coding agents can use the [repository skill](.agents/skills/polycolab-repository/SKILL.md) for development and checks.
Invoke the skill as `$polycolab-repository`.

## Common commands

1. Install the JavaScript dependencies from the lockfile:

   ```sh
   pnpm install --frozen-lockfile
   ```

2. Install the Python dependencies from the lockfile:

   ```sh
   uv --directory backend sync --all-groups --frozen
   ```

3. Run the repository's JavaScript and TypeScript checks:

   ```sh
   pnpm run check
   ```

## Repository map

| Directory              | Contents                                                       |
| ---------------------- | -------------------------------------------------------------- |
| `web/`                 | Svelte browser application                                     |
| `backend/`             | FastAPI services, database migrations, and private workers     |
| `packages/api-client/` | OpenAPI snapshot and generated TypeScript client               |
| `packages/brand/`      | Shared color tokens                                            |
| `tests/`               | Browser, backend, execution, and system checks                 |
| `deploy/`              | Deployment configuration and operator guides                   |
| `docs/`                | Product requirements, implementation architecture, and roadmap |
| `docs-site/`           | Public documentation for users and developers                  |
| `skills/`              | Instructions for external agents that use Polycolab            |
| `.agents/skills/`      | Skills for coding agents that work on this repository          |

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
- The community consumer.
- The reconciler for hosted runs.
- The artifact cleanup process.

The local services store accounts and research in `.local/polycolab.db`.
They store uploads in `.local/artifacts/`.
This data persists across restarts.

Before startup, the command applies pending SQLite migrations.
Before an upgrade, it saves a backup of the existing database in `.local/backups/`.
A failed upgrade stops startup.
It never resets your data.

Press Ctrl+C to stop all processes that the command starts.
Restart the command after changes to `deploy/docker/.env`.
Source changes reload automatically.

### Run with Docker

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
They do not read `.env` files from the repository root, `backend/`, or legacy deployment directories.
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
See the [third-party notices](THIRD_PARTY_NOTICES.md).
