from __future__ import annotations

import hashlib
import sqlite3
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, create_engine

from polycolab.artifacts.storage import (
    ArtifactIntegrity,
    ArtifactStorageError,
    FilesystemStorage,
    new_staging_key,
)
from polycolab.db.base import Base
from polycolab.operations.local_development import upgrade_database


def test_local_schema_matches_models_and_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "local.db"
    assert upgrade_database(path) is None
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    reference = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(reference)
    expected = MetaData()
    expected.reflect(reference)
    actual = create_engine(f"sqlite:///{path}")
    with actual.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), expected)
        assert [
            change
            for change in differences
            if not (change[0] == "remove_table" and change[1].name == "alembic_version")
        ] == []
    actual.dispose()
    reference.dispose()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM projects").fetchone() == (0,)
        db.execute("CREATE TABLE user_marker (value TEXT)")
        db.execute("INSERT INTO user_marker VALUES ('retained')")
    assert upgrade_database(path) is None
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM user_marker").fetchone() == ("retained",)


def test_unversioned_database_is_not_stamped(tmp_path: Path) -> None:
    path = tmp_path / "existing.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE important_data (value TEXT)")
    with pytest.raises(RuntimeError, match="Unversioned"):
        upgrade_database(path)


def test_local_upgrade_backs_up_and_rolls_back_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from polycolab.operations import local_development as local

    path = tmp_path / "local.db"
    upgrade_database(path)
    migrations = tmp_path / "migrations"
    shutil.copytree(local.MIGRATIONS, migrations)
    next_revision = migrations / "versions/next.py"
    next_revision.write_text("""from alembic import op
revision = "local_next"
down_revision = "local_20261029_workspace_only"
def upgrade():
    op.execute("CREATE TABLE migration_marker (value TEXT)")
    op.execute("INSERT INTO migration_marker VALUES ('upgraded')")
""")
    monkeypatch.setattr(local, "MIGRATIONS", migrations)
    backup = upgrade_database(path)
    assert backup is not None and backup.is_file()
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "local_20261029_workspace_only",
        )
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM migration_marker").fetchone() == ("upgraded",)
    (migrations / "versions/failure.py").write_text("""from alembic import op
revision = "local_failure"
down_revision = "local_next"
def upgrade():
    op.execute("DROP TABLE migration_marker")
    raise RuntimeError("test migration failure")
""")
    with pytest.raises(RuntimeError, match="test migration failure"):
        upgrade_database(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM migration_marker").fetchone() == ("upgraded",)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("local_next",)


def test_filesystem_integrity_and_safe_keys(tmp_path: Path) -> None:
    storage = FilesystemStorage(tmp_path / "blobs")
    key = new_staging_key()
    body = b"research artifact"
    integrity = ArtifactIntegrity(hashlib.sha256(body).hexdigest(), len(body))
    storage.put_verified(key, BytesIO(body), integrity)
    assert FilesystemStorage(storage.root).get_verified(key, integrity) == body
    with pytest.raises(ArtifactStorageError):
        storage.put_verified(key, BytesIO(body), integrity)
    with pytest.raises(ArtifactStorageError):
        storage.get_verified("../../outside", integrity)
    (storage.root / key).write_bytes(b"corrupt")
    with pytest.raises(ArtifactStorageError):
        storage.get_verified(key, integrity)
    interrupted = storage.root / "artifacts" / f".{key.split('/')[1]}.tmp"
    interrupted.write_bytes(b"interrupted upload")
    storage.delete(key)
    assert not interrupted.exists()
    storage.delete(key)
    outside = tmp_path / "outside"
    outside.write_bytes(body)
    (storage.root / key).symlink_to(outside)
    with pytest.raises(ArtifactStorageError):
        storage.get_verified(key, integrity)
    storage.delete(key)
    assert outside.read_bytes() == body
    bad_key = new_staging_key()
    with pytest.raises(ArtifactStorageError):
        storage.put_verified(bad_key, BytesIO(b"wrong"), integrity)
    assert not (storage.root / bad_key).exists()


@pytest.mark.parametrize(
    "previous",
    [
        "local_20260916_key_reveal",
        "local_20260916_versions",
        "local_20261014_chat",
        "local_20261013_document_builds",
    ],
)
def test_local_upgrade_from_either_merged_branch(tmp_path: Path, previous: str) -> None:
    from alembic import command
    from alembic.config import Config

    from polycolab.operations.local_development import MIGRATIONS

    path = tmp_path / "existing.db"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, previous)
        connection.exec_driver_sql("CREATE TABLE user_marker (value TEXT)")
        connection.exec_driver_sql("INSERT INTO user_marker VALUES ('retained')")
    engine.dispose()
    assert upgrade_database(path) is not None
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM user_marker").fetchone() == ("retained",)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "local_20261029_workspace_only",
        )
        assert "encrypted_secret" in {
            row[1] for row in db.execute("PRAGMA table_info(external_agent_credentials)")
        }
        assert db.execute(
            "SELECT count(*) FROM sqlite_master WHERE name = 'research_objects'"
        ).fetchone() == (0,)
        for table in (
            "chat_conversations",
            "chat_turns",
            "document_builds",
            "document_build_queue",
        ):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)


def test_provider_preview_upgrade_preserves_existing_encrypted_credentials(
    tmp_path: Path,
) -> None:
    from alembic import command
    from alembic.config import Config

    from polycolab.operations.local_development import MIGRATIONS

    path = tmp_path / "existing-provider.db"
    engine = create_engine(f"sqlite:///{path}")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "local_20261011_native_worktrees")
        owner_id = uuid4().hex
        connection.exec_driver_sql(
            "INSERT INTO users (id, issuer, subject, created_at, updated_at) "
            "VALUES (?, 'test', 'preview-owner', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (owner_id,),
        )
        connection.exec_driver_sql(
            "INSERT INTO gateway_profiles "
            "(id, user_id, display_name, base_url, model_id, wire_api, credential_version, "
            "encrypted_credential, wrapped_data_key, encryption_key_version, "
            "created_at, updated_at) "
            "VALUES (?, ?, 'Existing', 'https://example.com/v1', 'model', 'responses', 1, "
            "?, ?, 'local-v1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (uuid4().hex, owner_id, b"encrypted-fixture", b"wrapped-fixture"),
        )
        command.upgrade(config, "head")
        assert connection.exec_driver_sql(
            "SELECT api_key_preview, encrypted_credential, wrapped_data_key FROM gateway_profiles"
        ).one() == (None, b"encrypted-fixture", b"wrapped-fixture")
    engine.dispose()
