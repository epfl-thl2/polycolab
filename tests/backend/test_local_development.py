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
        assert db.execute("SELECT count(*) FROM research_scopes").fetchone() == (1,)
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
down_revision = "local_20261013_agent_library"
def upgrade():
    op.execute("CREATE TABLE migration_marker (value TEXT)")
    op.execute("INSERT INTO migration_marker VALUES ('upgraded')")
""")
    monkeypatch.setattr(local, "MIGRATIONS", migrations)
    backup = upgrade_database(path)
    assert backup is not None and backup.is_file()
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "local_20261013_agent_library",
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


def test_local_real_accounts_research_and_uploads_persist(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    from pydantic import AnyUrl, SecretStr

    from polycolab.app.application import create_app
    from polycolab.platform.config import RegistrationMode, Settings

    database = tmp_path / "polycolab.db"
    from alembic import command
    from alembic.config import Config

    from polycolab.operations.local_development import MIGRATIONS

    baseline = create_engine(f"sqlite:///{database}")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with baseline.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "local_20260916")
    baseline.dispose()
    origin = "http://localhost:5174"
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{database}",
        artifact_local_directory=tmp_path / "artifacts",
        public_app_origin=AnyUrl(origin),
        registration_mode=RegistrationMode.OPEN,
        bootstrap_admin_password=SecretStr("local-test-password-long"),
        web_dist_dir=str(tmp_path / "no-web"),
    )
    from polycolab.accounts.builtin import hash_password

    account_id, user_id = uuid4(), uuid4().hex
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO local_accounts (id, username, password_digest, display_name, "
            "is_admin, created_at, updated_at) "
            "VALUES (?, 'localresearcher', ?, 'Local researcher', 0, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (account_id.hex, hash_password("local-test-password-long")),
        )
        db.execute(
            "INSERT INTO users (id, issuer, subject, display_name, created_at, updated_at) "
            "VALUES (?, 'polycolab-local', ?, 'Local researcher', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (user_id, str(account_id)),
        )
    app = create_app(settings)
    headers = {"Origin": origin, "Idempotency-Key": "local-copy"}
    with TestClient(app, base_url=origin) as client:
        registered = client.post(
            "/auth/login",
            headers=headers,
            json={
                "username": "localresearcher",
                "password": "local-test-password-long",
            },
        )
        assert registered.status_code == 200, registered.text
        # Seed the historical project classification directly; new binaries cannot
        # create projects until the forward migration has run.
        project_id = str(uuid4())
        with sqlite3.connect(database) as db:
            db.execute(
                "INSERT INTO projects "
                "(id, name, visibility, created_by_user_id, created_at, updated_at) "
                "VALUES (?, 'Persistent local research', 'PRIVATE', ?, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (project_id.replace("-", ""), user_id),
            )
            db.execute(
                "INSERT INTO memberships (id, project_id, user_id, role, created_at, updated_at) "
                "VALUES (?, ?, ?, 'OWNER', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (uuid4().hex, project_id.replace("-", ""), user_id),
            )
            db.execute(
                "INSERT INTO research_scopes (id, scope_kind, project_id, created_at) "
                "VALUES (?, 'WORKSPACE', ?, CURRENT_TIMESTAMP)",
                (uuid4().hex, project_id.replace("-", "")),
            )
        # Seed the frozen baseline directly: the current API must not write an old schema.
        version_id, object_id, contribution_id = (uuid4().hex for _ in range(3))
        with sqlite3.connect(database) as db:
            project_hex = project_id.replace("-", "")
            user_id = db.execute(
                "SELECT created_by_user_id FROM projects WHERE id = ?", (project_hex,)
            ).fetchone()[0]
            scope_id = db.execute(
                "SELECT id FROM research_scopes WHERE project_id = ?", (project_hex,)
            ).fetchone()[0]
            db.execute(
                "INSERT INTO contribution_envelopes "
                "(id, actor_kind, human_user_id, ownership_scope_id, project_id, operation, "
                "source_event_cursors, created_at) VALUES (?, 'HUMAN', ?, ?, ?, "
                "'object.create', '{}', CURRENT_TIMESTAMP)",
                (contribution_id, user_id, scope_id, project_hex),
            )
            db.execute(
                "INSERT INTO research_objects (id, ownership_scope_id, entity_class, kind, "
                "current_revision_id, contribution_id, created_by_user_id, provenance_kind, "
                "created_at, updated_at) VALUES (?, ?, 'STATEMENT', 'CLAIM', ?, ?, ?, "
                "'HUMAN_DIRECT', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (object_id, scope_id, version_id, contribution_id, user_id),
            )
            db.execute(
                "INSERT INTO object_revisions (id, ownership_scope_id, object_id, schema_version, "
                "number, title, content_md, contribution_id, created_by_user_id, provenance_kind, "
                "created_at) VALUES (?, ?, ?, 1, 1, 'Local claim', "
                "'A local mathematical statement', ?, ?, 'HUMAN_DIRECT', CURRENT_TIMESTAMP)",
                (version_id, scope_id, object_id, contribution_id, user_id),
            )
            db.execute(
                "INSERT INTO statement_revisions (revision_id, kind, assumptions_md) "
                "VALUES (?, 'CLAIM', '')",
                (version_id,),
            )
            later_id = uuid4().hex
            db.execute(
                "INSERT INTO object_revisions (id, ownership_scope_id, object_id, schema_version, "
                "number, title, content_md, base_revision_id, contribution_id, created_by_user_id, "
                "provenance_kind, created_at) VALUES (?, ?, ?, 1, 2, 'Later local claim', "
                "'Later snapshot', ?, ?, ?, 'HUMAN_DIRECT', CURRENT_TIMESTAMP)",
                (later_id, scope_id, object_id, version_id, contribution_id, user_id),
            )
            db.execute(
                "INSERT INTO statement_revisions (revision_id, kind, assumptions_md) "
                "VALUES (?, 'CLAIM', '')",
                (later_id,),
            )
            db.execute(
                "UPDATE research_objects SET current_revision_id = ? WHERE id = ?",
                (later_id, object_id),
            )
            db.execute(
                "INSERT INTO research_attachments (revision_id, statement_revision_id) "
                "VALUES (?, ?)",
                (later_id, version_id),
            )
            declarations = [uuid4().hex, uuid4().hex]
            for relationship_id, kind in zip(declarations, ("USES", "EQUIVALENT_TO"), strict=True):
                db.execute(
                    "INSERT INTO relation_assertions (id, ownership_scope_id, source_revision_id, "
                    "target_revision_id, relation_type, rationale, contribution_id, "
                    "created_by_user_id, provenance_kind, created_at) VALUES (?, ?, ?, ?, ?, "
                    "'Original relation', ?, ?, 'HUMAN_DIRECT', CURRENT_TIMESTAMP)",
                    (
                        relationship_id,
                        scope_id,
                        later_id,
                        version_id,
                        kind,
                        contribution_id,
                        user_id,
                    ),
                )
        # Upgrade an actual account and research project from main's baseline.
        assert upgrade_database(database) is not None
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone() == (
                "localresearcher",
            )
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
            assert db.execute("SELECT count(*) FROM object_version_relationships").fetchone() == (
                3,
            )
            assert db.execute(
                "SELECT source_object_version_id, target_object_version_id "
                "FROM object_version_relationships WHERE id = ?",
                (declarations[0],),
            ).fetchone() == (later_id, version_id)
            assert db.execute(
                "SELECT first_object_version_id, second_object_version_id "
                "FROM object_version_relationships WHERE id = ?",
                (declarations[1],),
            ).fetchone() == tuple(sorted((later_id, version_id)))
            assert db.execute(
                "SELECT target_object_version_id FROM object_version_relationships "
                "WHERE binding = 'STRUCTURAL'"
            ).fetchone() == (version_id,)
        record = client.get(f"/api/v1/versions/{version_id}")
        assert record.status_code == 200, record.text
        assert record.json()["content"]["content_md"] == "A local mathematical statement"
        body = b"persistent evidence"
        upload = client.post(
            "/api/v1/artifacts",
            headers=headers,
            content=body,
            params={
                "project_id": project_id,
                "sha256": hashlib.sha256(body).hexdigest(),
                "byte_length": len(body),
            },
        )
        assert upload.status_code == 201, upload.text
        artifact_id = upload.json()["id"]
        attachment = client.post(
            "/api/v1/attachments",
            headers=headers,
            json={
                "artifact_id": artifact_id,
                "object_version_id": record.json()["id"],
                "role": "EVIDENCE",
            },
        )
        assert attachment.status_code == 200, attachment.text
        url = f"/api/v1/artifacts/{artifact_id}/content"
        assert client.get(url).content == body
    app.state.engine.dispose()
    assert upgrade_database(database) is None
    app = create_app(settings)
    with TestClient(app, base_url=origin) as client:
        assert client.get(url).status_code in (401, 404)
        signed_in = client.post(
            "/auth/login",
            headers=headers,
            json={
                "username": "localresearcher",
                "password": "local-test-password-long",
            },
        )
        assert signed_in.status_code == 200, signed_in.text
        assert client.get(url).content == body
        assert (
            client.get(f"/api/v1/projects/{project_id}").json()["name"]
            == "Persistent local research"
        )
    app.state.engine.dispose()


@pytest.mark.parametrize("previous", ["local_20260916_key_reveal", "local_20260916_versions"])
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
            "local_20261013_agent_library",
        )
        assert "encrypted_secret" in {
            row[1] for row in db.execute("PRAGMA table_info(external_agent_credentials)")
        }
        assert db.execute("SELECT count(*) FROM object_version_relationships").fetchone() == (0,)


def test_provider_preview_upgrade_preserves_existing_encrypted_credentials(tmp_path: Path) -> None:
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
