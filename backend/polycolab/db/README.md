# Database implementation

Use these directories to find SQL persistence code:

| Location                 | Responsibility                                                                                            |
| ------------------------ | --------------------------------------------------------------------------------------------------------- |
| `models/`                | `Sql`-prefixed classes mapped to tables or queries. The package initializer registers every mapped class. |
| `stores/`                | Implements SQL reads, writes, and locking through capability store interfaces.                            |
| `converters/`            | Converts SQL rows into application entities without issuing queries.                                      |
| `migrations/postgresql/` | Production Alembic environment and PostgreSQL revision history.                                           |
| `migrations/sqlite/`     | Local-development Alembic environment, SQLite revisions, and frozen schemas.                              |
| `base.py`                | The single declarative base and metadata.                                                                 |
| `session.py`             | Engines, connection pools, session factories, and readiness checks.                                       |
| `transaction.py`         | SQLAlchemy transaction implementation shared by participating stores.                                     |
| `errors.py`              | Translates SQLAlchemy exceptions into application persistence errors.                                     |

Files within models, stores, and converters are grouped by subject, such as `accounts.py` and `research.py`.
Query-mapped classes stay beside related table models.
Import `Base` from `polycolab.db.base` and timestamp values from `polycolab.entities.time` directly.

The application calls a store, which queries SQL models, uses converters, and returns application entities.
Store interfaces live in the owning capability's `store.py`.
Application values live in `entities/`.
Built-in password and browser session workflows live in `accounts/builtin.py`.

`polycolab.transaction.Transaction` defines the shared application contract.
`SqlAlchemyTransaction` gives its stores one session.
Stores may flush.
The coordinating operation owns commits.
Uncommitted contexts roll back on exit.
Borrowed request sessions remain owned by request composition.

Run PostgreSQL migrations with the existing `pnpm run api:migrate` command.
SQLite local development selects its separate history automatically.
These separate histories preserve revision IDs and existing database version records.

Persistence isolation is still partial: some services retain direct SQL access.
See the [persistence architecture](../../../docs/architecture/persistence.md) for implemented boundaries and remaining conversion work.
