"""SQLite-only migration environment; callers supply a checked local connection."""

from alembic import context

connection = context.config.attributes["connection"]
context.configure(connection=connection, render_as_batch=True, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
