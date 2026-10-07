from __future__ import annotations

from collections.abc import Generator
from datetime import timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import AnyUrl
from sqlalchemy import func, select

from polycolab.accounts.builtin import bootstrap_admin
from polycolab.app.application import create_app
from polycolab.db.base import Base
from polycolab.db.models import (
    SqlAuthSession,
    SqlLocalAccount,
    SqlMembership,
    SqlRegistrationInvitation,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import InvitationStatus
from polycolab.entities.time import utc_now
from polycolab.platform.config import AuthMode, RegistrationMode, Settings

ORIGIN = "https://registration.example"
PASSWORD = "correct horse battery staple"


def _client(
    tmp_path: Path,
    *,
    mode: RegistrationMode = RegistrationMode.OPEN,
    rate: int = 100,
    max_bytes: int = 4096,
) -> Generator[TestClient]:
    app = create_app(
        Settings(
            database_url="sqlite+pysqlite:///:memory:",
            web_dist_dir=str(tmp_path / "missing-web"),
            public_app_origin=AnyUrl(ORIGIN),
            registration_mode=mode,
            registration_requests_per_minute=rate,
            registration_max_request_bytes=max_bytes,
        )
    )
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as session:
        bootstrap_admin(SqlAlchemyTransaction(session), PASSWORD)
    with TestClient(app, base_url=ORIGIN) as client:
        yield client
    Base.metadata.drop_all(app.state.engine)
    app.state.engine.dispose()


@pytest.fixture
def open_client(tmp_path: Path) -> Generator[TestClient]:
    yield from _client(tmp_path)


@pytest.fixture
def invitation_client(tmp_path: Path) -> Generator[TestClient]:
    yield from _client(tmp_path, mode=RegistrationMode.INVITATION)


def _setup(client: TestClient) -> None:
    response = client.post("/auth/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 200


def _register(
    client: TestClient,
    username: str,
    *,
    invitation_code: str | None = None,
    origin: str | None = ORIGIN,
) -> Response:
    payload = {"username": username, "password": PASSWORD, "display_name": "New user"}
    if invitation_code is not None:
        payload["invitation_code"] = invitation_code
    headers = {"Origin": origin} if origin is not None else {}
    return cast(Response, client.post("/auth/register", headers=headers, json=payload))


def test_closed_default_and_oidc_do_not_expose_enrollment(tmp_path: Path) -> None:
    closed_app = create_app(
        Settings(
            database_url="sqlite+pysqlite:///:memory:",
            web_dist_dir=str(tmp_path / "closed"),
        )
    )
    Base.metadata.create_all(closed_app.state.engine)
    with TestClient(closed_app, base_url=ORIGIN) as client:
        assert client.get("/auth/config").json()["registration_mode"] == "closed"
        response = _register(client, "alice")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "registration_closed"
    closed_app.state.engine.dispose()

    oidc_app = create_app(
        Settings(
            auth_mode=AuthMode.OIDC,
            oidc_issuer=AnyUrl("https://issuer.example"),
            oidc_jwks_url=AnyUrl("https://issuer.example/keys"),
            oidc_audience="polycolab",
            oidc_authorized_party="browser",
            oidc_client_id="browser",
            database_url="sqlite+pysqlite:///:memory:",
            web_dist_dir=str(tmp_path / "oidc"),
        )
    )
    Base.metadata.create_all(oidc_app.state.engine)
    with TestClient(oidc_app, base_url=ORIGIN) as client:
        assert "registration_mode" not in client.get("/auth/config").json()
        assert _register(client, "alice").status_code == 404
    oidc_app.state.engine.dispose()


def test_open_registration_requires_bootstrap_origin_and_creates_ordinary_session_atomically(
    open_client: TestClient,
) -> None:
    _setup(open_client)
    open_client.post("/auth/logout")
    assert _register(open_client, "alice", origin=None).status_code == 403
    assert _register(open_client, "alice", origin="https://attacker.example").status_code == 403
    created = _register(open_client, "  Alice  ")
    assert created.status_code == 201
    assert created.json() == {
        "authenticated": True,
        "username": "alice",
        "display_name": "New user",
        "is_admin": False,
    }
    assert "HttpOnly" in created.headers["set-cookie"]
    assert created.headers["cache-control"] == "no-store"
    app = open_client.app
    assert isinstance(app, FastAPI)
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(SqlLocalAccount)) == 2
        assert session.scalar(select(func.count()).select_from(SqlAuthSession)) == 2
        assert session.scalar(select(func.count()).select_from(SqlMembership)) == 0

    open_client.post("/auth/logout")
    login = open_client.post("/auth/login", json={"username": "alice", "password": PASSWORD})
    assert login.status_code == 200


def test_registration_rejects_privilege_email_terms_and_invalid_credentials(
    open_client: TestClient,
) -> None:
    _setup(open_client)
    open_client.post("/auth/logout")
    for extra in (
        {"is_admin": True},
        {"email": "alice@example.test"},
        {"terms_accepted": True},
    ):
        response = open_client.post(
            "/auth/register",
            headers={"Origin": ORIGIN},
            json={"username": "alice", "password": PASSWORD, **extra},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
    weak = open_client.post(
        "/auth/register",
        headers={"Origin": ORIGIN},
        json={"username": "alice", "password": "too short"},
    )
    assert weak.status_code == 422
    duplicate = _register(open_client, "admin")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "registration_conflict"


def test_registration_body_and_durable_address_rate_are_enforced_before_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_context = _client(tmp_path, rate=1, max_bytes=512)
    client = next(client_context)
    try:
        _setup(client)
        client.post("/auth/logout")
        assert _register(client, "alice").status_code == 201

        def unexpected_hash(_: str) -> str:
            raise AssertionError("rate-limited request reached password hashing")

        monkeypatch.setattr("polycolab.accounts.builtin.hash_password", unexpected_hash)
        limited = _register(client, "bob")
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "registration_rate_limited"
        assert limited.headers["retry-after"]
        oversized = client.post(
            "/auth/register",
            headers={"Origin": ORIGIN},
            content=b"x" * 513,
        )
        assert oversized.status_code == 413
        assert oversized.json()["error"]["code"] == "registration_request_too_large"
    finally:
        try:
            next(client_context)
        except StopIteration:
            pass


def test_registration_admission_dependency_failure_is_content_free_and_skips_hashing(
    open_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(open_client)
    open_client.post("/auth/logout")

    def unavailable(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic admission dependency failure")

    def unexpected_hash(_: str) -> str:
        raise AssertionError("dependency-failed request reached password hashing")

    monkeypatch.setattr("polycolab.app.application.enforce_registration_limit", unavailable)
    monkeypatch.setattr("polycolab.accounts.builtin.hash_password", unexpected_hash)
    response = _register(open_client, "alice")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert PASSWORD not in response.text
    assert "set-cookie" not in response.headers


def test_invitation_issuance_consumption_replay_and_admin_boundaries(
    invitation_client: TestClient,
) -> None:
    _setup(invitation_client)
    issued = invitation_client.post(
        "/auth/registration/invitations", headers={"Origin": ORIGIN}, json={}
    )
    assert issued.status_code == 201
    code = issued.json()["code"]
    assert len(code) >= 32
    listing = invitation_client.get("/auth/registration/invitations")
    assert listing.status_code == 200
    assert listing.json()[0]["status"] == "pending"
    assert "code" not in listing.json()[0]

    invitation_client.post("/auth/logout")
    missing = _register(invitation_client, "alice")
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "invalid_registration_invitation"
    created = _register(invitation_client, "alice", invitation_code=code)
    assert created.status_code == 201
    assert created.json()["is_admin"] is False
    replay = _register(invitation_client, "bob", invitation_code=code)
    assert replay.status_code == 400
    assert code not in replay.text

    forbidden = invitation_client.post(
        "/auth/registration/invitations", headers={"Origin": ORIGIN}, json={}
    )
    assert forbidden.status_code == 403
    app = invitation_client.app
    assert isinstance(app, FastAPI)
    with app.state.session_factory() as session:
        row = session.scalar(select(SqlRegistrationInvitation))
        assert row is not None
        assert row.status is InvitationStatus.ACCEPTED
        assert row.accepted_by_account_id is not None


def test_revoked_and_expired_invitations_fail_without_accounts(
    invitation_client: TestClient,
) -> None:
    _setup(invitation_client)
    first = invitation_client.post(
        "/auth/registration/invitations", headers={"Origin": ORIGIN}, json={}
    ).json()
    revoked = invitation_client.delete(
        f"/auth/registration/invitations/{first['id']}", headers={"Origin": ORIGIN}
    )
    assert revoked.status_code == 204
    second = invitation_client.post(
        "/auth/registration/invitations", headers={"Origin": ORIGIN}, json={}
    ).json()
    app = invitation_client.app
    assert isinstance(app, FastAPI)
    with app.state.session_factory() as session:
        row = session.get(SqlRegistrationInvitation, UUID(second["id"]))
        assert row is not None
        row.created_at = utc_now() - timedelta(days=2)
        row.expires_at = utc_now() - timedelta(days=1)
        session.commit()
    invitation_client.post("/auth/logout")
    assert _register(invitation_client, "alice", invitation_code=first["code"]).status_code == 400
    assert _register(invitation_client, "bob", invitation_code=second["code"]).status_code == 400
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(SqlLocalAccount)) == 1
