"""Existing published library content and retry records survive terminology upgrades."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import DBAPIError

from polycolab.entities.time import utc_now
from polycolab.operations.local_development import MIGRATIONS


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
def test_populated_library_upgrade(
    request: pytest.FixtureRequest, tmp_path: Path, dialect: str
) -> None:
    if dialect == "postgresql":
        engine, config, _ = request.getfixturevalue("pg_schema")
        prefix = ""
    else:
        engine = sa.create_engine(f"sqlite:///{tmp_path / 'library.db'}")
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS))
        prefix = "local_"
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, prefix + "20261115_file_modes")
        metadata = sa.MetaData()
        metadata.reflect(connection)

        def key(identifier: UUID) -> UUID | str:
            return identifier.hex if dialect == "sqlite" else identifier

        def insert(table: str, **values: object) -> None:
            connection.execute(metadata.tables[table].insert().values(**values))

        now = utc_now()
        owner, item_id, version_id = [key(uuid4()) for _ in range(3)]
        content = {
            "title": "Retained",
            "description": "Original",
            "content": "Keep exact text\n",
            "license": "CC0",
        }
        insert(
            "users",
            id=owner,
            issuer="migration",
            subject=str(owner),
            created_at=now,
            updated_at=now,
        )
        insert(
            "agent_library_entries",
            id=item_id,
            owner_user_id=owner,
            kind="PROMPT",
            revision=2,
            archived=False,
            hidden=False,
            created_at=now,
        )
        insert("agent_library_drafts", entry_id=item_id, content=content)
        insert(
            "agent_library_versions",
            id=version_id,
            entry_id=item_id,
            number=1,
            content=content,
            author_user_id=owner,
            author_name="Original author",
            published_at=now,
        )
        connection.execute(
            metadata.tables["agent_library_entries"]
            .update()
            .values(published_version_id=version_id)
        )
        insert(
            "agent_library_moderation",
            id=key(uuid4()),
            entry_id=item_id,
            actor_user_id=owner,
            hidden=False,
            reason="Original audit",
            created_at=now,
        )
        insert(
            "mutation_receipts",
            id=key(uuid4()),
            actor_key=f"human:{owner}",
            operation="agent_library.publish",
            idempotency_key_digest="a" * 64,
            request_digest="b" * 64,
            status="COMMITTED",
            resource_ids=[str(version_id)],
            created_at=now,
        )
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        current = sa.MetaData()
        current.reflect(connection)
        assert "agent_library_entries" not in current.tables
        saved = connection.execute(sa.select(current.tables["library_items"])).mappings().one()
        assert saved["id"] == item_id
        assert saved["published_version_id"] == version_id
        for name in ("library_versions", "library_drafts"):
            value = connection.execute(sa.select(current.tables[name])).mappings().one()
            assert value["item_id"] == item_id
            assert value["content"] == content
        retry = (
            connection.execute(sa.select(current.tables["idempotency_records"])).mappings().one()
        )
        assert retry["operation"] == "agent_library.publish"
        assert retry["request_digest"] == "b" * 64
        assert retry["resource_ids"] == [str(version_id)]
    # Trigger guards must survive SQLite table recreation as well as PG renames.
    for name, field, value in [
        ("library_versions", "author_name", "Changed"),
        ("library_moderation", "reason", "Changed"),
        ("library_items", "kind", "SKILL"),
    ]:
        with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                connection.execute(current.tables[name].update().values(**{field: value}))
            connection.rollback()
    if dialect == "sqlite":
        engine.dispose()
