"""Migration orchestration with SQLite/local crypto, not live vault evidence."""

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.engine import Connection
from test_gateway import app_for, create_gateway_profile

from polycolab.db.models import SqlGatewayCredentialRewrapAudit, SqlGatewayProfile
from polycolab.model_gateway import rewrap as credential_rewrap
from polycolab.model_gateway.credentials import LocalAesGcmKeyWrapper
from polycolab.model_gateway.migration import CredentialKeyring, commit_rewrap_candidate
from polycolab.model_gateway.rewrap import main, migrate_page


def ring_for(client: TestClient) -> CredentialKeyring:
    return CredentialKeyring(
        [app_for(client).state.credential_wrapper, LocalAesGcmKeyWrapper(b"b" * 32, "target-v2")]
    )


def test_dry_run_and_resume_with_no_transaction_during_key_io(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_gateway_profile(client)
    create_gateway_profile(client, "contributor")
    app, ring = app_for(client), ring_for(client)
    active: set[int] = set()
    event.listen(app.state.engine, "begin", lambda connection: active.add(id(connection)))

    def ended(connection: Connection) -> None:
        active.discard(id(connection))

    event.listen(app.state.engine, "commit", ended)
    event.listen(app.state.engine, "rollback", ended)
    prepare = ring.prepare_rewrap
    calls = 0

    def checked(**kwargs: Any) -> Any:
        nonlocal calls
        assert not active
        calls += 1
        return prepare(**kwargs)

    monkeypatch.setattr(ring, "prepare_rewrap", checked)
    dry = migrate_page(app.state.session_factory, ring)
    assert dry.status == "DRY_RUN" and dry.selected == 2 and calls == 0
    first = migrate_page(app.state.session_factory, ring, apply=True, limit=1)
    assert first.migrated == 1 and first.more_may_remain
    second = migrate_page(app.state.session_factory, ring, apply=True)
    assert second.migrated == 1 and not second.more_may_remain
    assert migrate_page(app.state.session_factory, ring, apply=True).selected == 0
    assert calls == 2 and not active
    with app.state.session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(SqlGatewayCredentialRewrapAudit)) == 2
        )


def test_partial_failure_resumes_from_committed_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_gateway_profile(client)
    create_gateway_profile(client, "contributor")
    app, ring = app_for(client), ring_for(client)
    prepare = ring.prepare_rewrap
    calls = 0

    def interrupted(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic-secret-upstream-error")
        return prepare(**kwargs)

    monkeypatch.setattr(ring, "prepare_rewrap", interrupted)
    report = migrate_page(app.state.session_factory, ring, apply=True)
    assert report.status == "KEY_FAILURE" and report.migrated == 1
    assert "synthetic-secret" not in repr(report)
    monkeypatch.setattr(ring, "prepare_rewrap", prepare)
    assert migrate_page(app.state.session_factory, ring, apply=True).migrated == 1
    with app.state.session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(SqlGatewayCredentialRewrapAudit)) == 2
        )


def test_concurrent_rotation_is_not_overwritten(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = create_gateway_profile(client)
    app, ring = app_for(client), ring_for(client)
    prepare = ring.prepare_rewrap

    def rotated(**kwargs: Any) -> Any:
        candidate = prepare(**kwargs)
        with app.state.session_factory() as session:
            profile = session.get(SqlGatewayProfile, UUID(created["id"]))
            assert profile is not None
            profile.credential_version += 1
            session.commit()
        return candidate

    monkeypatch.setattr(ring, "prepare_rewrap", rotated)
    result = migrate_page(app.state.session_factory, ring, apply=True)
    assert result.status == "CONFLICT" and result.migrated == 0
    with app.state.session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(SqlGatewayCredentialRewrapAudit)) == 0
        )
        profile = session.get(SqlGatewayProfile, UUID(created["id"]))
        assert profile is not None and profile.encryption_key_version != ring.key_version


@pytest.mark.parametrize("args", [["--apply"], ["--limit", "0"], ["--limit", "101"]])
def test_cli_rejects_unsafe_invocation_before_configuration(args: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2


def test_ambiguous_commit_is_resolved_by_rereading_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_gateway_profile(client)
    app, ring = app_for(client), ring_for(client)
    commit = commit_rewrap_candidate

    def ambiguous(*args: Any, **kwargs: Any) -> Any:
        commit(*args, **kwargs)
        raise RuntimeError("synthetic-secret-connection-error")

    monkeypatch.setattr(credential_rewrap, "commit_rewrap_candidate", ambiguous)
    report = migrate_page(app.state.session_factory, ring, apply=True)
    assert report.status == "DATABASE_FAILURE"
    monkeypatch.setattr(credential_rewrap, "commit_rewrap_candidate", commit)
    assert migrate_page(app.state.session_factory, ring, apply=True).selected == 0
    with app.state.session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(SqlGatewayCredentialRewrapAudit)) == 1
        )


def test_cli_does_not_print_configuration_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken() -> Any:
        raise ValueError("synthetic-secret-configuration")

    monkeypatch.setattr(credential_rewrap, "get_settings", broken)
    assert main([]) == 1
    captured = capsys.readouterr()
    assert "CONFIGURATION_OR_RUNTIME_FAILURE" in captured.out
    assert "synthetic-secret" not in captured.out + captured.err
