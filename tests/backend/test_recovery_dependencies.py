"""SQLite, fake S3 and local crypto evidence; no deployment acceptance."""

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.engine import Connection
from test_artifacts import artifact_client as artifact_client
from test_artifacts import upload
from test_gateway import app_for, create_gateway_profile
from workspace_support import create_project

from polycolab.db.models import (
    SqlGatewayProfile,
)
from polycolab.entities.time import utc_now
from polycolab.model_gateway.credentials import (
    LocalAesGcmKeyWrapper,
    credential_context,
    encrypt_credential,
)
from polycolab.operations import recovery_dependencies
from polycolab.operations.recovery_dependencies import (
    verify_artifacts,
    verify_credentials,
)


def test_restored_committed_artifacts_are_verified_outside_transaction(
    artifact_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = artifact_client
    project = create_project(client)
    assert upload(client, project).status_code == 201
    app = app_for(client)
    active: set[int] = set()
    event.listen(app.state.engine, "begin", lambda connection: active.add(id(connection)))

    def ended(connection: Connection) -> None:
        active.discard(id(connection))

    event.listen(app.state.engine, "commit", ended)
    event.listen(app.state.engine, "rollback", ended)
    storage = app.state.artifact_storage
    get = storage.client.get_object

    def checked(**kwargs: Any) -> Any:
        assert not active
        return get(**kwargs)

    monkeypatch.setattr(storage.client, "get_object", checked)
    result = verify_artifacts(app.state.session_factory, storage, max_items=1)
    assert result.status == "VERIFIED" and result.checked == 1
    for key in storage.client.objects:
        storage.client.objects[key] = b"bad"
    assert verify_artifacts(app.state.session_factory, storage).status == "DEPENDENCY_FAILURE"
    storage.client.objects.clear()
    result = verify_artifacts(app.state.session_factory, storage)
    assert result.status == "DEPENDENCY_FAILURE" and result.checked == 0


def test_credentials_include_retained_deleted_profiles_and_fail_on_wrong_key(
    client: TestClient,
) -> None:
    create_gateway_profile(client)
    create_gateway_profile(client, "contributor")
    app = app_for(client)
    with app.state.session_factory() as session:
        profile = session.scalar(select(SqlGatewayProfile))
        assert profile is not None
        profile.deleted_at = utc_now()
        session.commit()
    report = verify_credentials(app.state.session_factory, app.state.credential_wrapper)
    assert report.status == "VERIFIED" and report.checked == 2
    report = verify_credentials(
        app.state.session_factory, app.state.credential_wrapper, max_items=1
    )
    assert report.status == "LIMIT_REACHED" and report.checked == 1
    report = verify_credentials(app.state.session_factory, LocalAesGcmKeyWrapper(b"x" * 32))
    assert report.status == "DEPENDENCY_FAILURE" and report.checked == 0


def test_key_io_occurs_after_transaction_close(client: TestClient) -> None:
    create_gateway_profile(client)
    app = app_for(client)
    active: set[int] = set()
    event.listen(app.state.engine, "begin", lambda connection: active.add(id(connection)))

    def ended(connection: Connection) -> None:
        active.discard(id(connection))

    event.listen(app.state.engine, "commit", ended)
    event.listen(app.state.engine, "rollback", ended)

    class Reader:
        key_version = app.state.credential_wrapper.key_version

        def unwrap(self, wrapped_key: bytes, context: bytes) -> bytes:
            assert not active
            return bytes(app.state.credential_wrapper.unwrap(wrapped_key, context))

        def wrap(self, plaintext_key: bytes, context: bytes) -> bytes:
            raise AssertionError("verification must not wrap credentials")

    assert verify_credentials(app.state.session_factory, Reader()).status == "VERIFIED"


def test_credential_scan_crosses_page_boundary(client: TestClient) -> None:
    create_gateway_profile(client)
    app = app_for(client)
    with app.state.session_factory() as session:
        source = session.scalar(select(SqlGatewayProfile))
        assert source is not None
        for _ in range(100):
            profile_id = uuid4()
            encrypted = encrypt_credential(
                app.state.credential_wrapper,
                context=credential_context(user_id=source.user_id, profile_id=profile_id),
                secret="synthetic-recovery-key",
            )
            session.add(
                SqlGatewayProfile(
                    id=profile_id,
                    user_id=source.user_id,
                    display_name="test",
                    base_url=source.base_url,
                    model_id=source.model_id,
                    encrypted_credential=encrypted.ciphertext,
                    wrapped_data_key=encrypted.wrapped_key,
                    encryption_key_version=encrypted.key_version,
                )
            )
        session.commit()
    report = verify_credentials(
        app.state.session_factory, app.state.credential_wrapper, max_items=101
    )
    assert report.status == "VERIFIED" and report.checked == 101
    report = verify_credentials(
        app.state.session_factory, app.state.credential_wrapper, max_items=100
    )
    assert report.status == "LIMIT_REACHED" and report.checked == 100


def test_cli_sanitizes_configuration_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failed() -> Any:
        raise RuntimeError("private-key-and-database-url")

    monkeypatch.setattr(recovery_dependencies, "get_settings", failed)
    assert recovery_dependencies.main(["credentials", "--isolated-restore"]) == 1
    assert capsys.readouterr().out == '{"status": "CONFIGURATION_OR_RUNTIME_FAILURE"}\n'


@pytest.mark.parametrize("max_items", [0, -1, 1_000_001, True])
def test_invalid_scan_bounds_are_rejected(client: TestClient, max_items: int) -> None:
    app = app_for(client)
    with pytest.raises(ValueError, match="invalid item bound"):
        verify_credentials(
            app.state.session_factory, app.state.credential_wrapper, max_items=max_items
        )


def test_database_failure_is_not_reported_as_verified(client: TestClient) -> None:
    app = app_for(client)

    def failed(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("private-database-details")

    event.listen(app.state.engine, "before_cursor_execute", failed)
    try:
        report = verify_credentials(app.state.session_factory, app.state.credential_wrapper)
        assert report.status == "DATABASE_FAILURE" and report.checked == 0
    finally:
        event.remove(app.state.engine, "before_cursor_execute", failed)
