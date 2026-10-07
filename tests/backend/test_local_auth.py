from __future__ import annotations

from collections.abc import Generator
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from polycolab.accounts.builtin import bootstrap_admin
from polycolab.app.application import create_app
from polycolab.db.base import Base
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.platform.config import AuthMode, Environment, KmsProvider, Settings


@pytest.fixture(params=list(Environment))
def local_client(request: pytest.FixtureRequest) -> Generator[TestClient]:
    app = create_app(
        Settings(
            app_env=request.param,
            database_url="sqlite+pysqlite:///:memory:",
            kms_provider=KmsProvider.AWS,
            kms_key_id="test-kms-key",
            admission_scope_hmac_key=SecretStr("test-admission-key"),
            runtime_worker_token=SecretStr("test-runtime-worker-token"),
        )
    )
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as session:
        bootstrap_admin(SqlAlchemyTransaction(session), "correct horse battery staple")
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    Base.metadata.drop_all(app.state.engine)
    app.state.engine.dispose()


def test_bootstrapped_admin_authenticates_api(local_client: TestClient) -> None:
    assert local_client.get("/auth/me").json() == {"authenticated": False}
    login = local_client.post(
        "/auth/login", json={"username": "admin", "password": "correct horse battery staple"}
    )
    assert login.status_code == 200
    assert login.json() == {
        "authenticated": True,
        "username": "admin",
        "display_name": "Admin",
        "is_admin": True,
    }
    assert "polycolab_session=" in login.headers["set-cookie"]
    # Explicit invalid bearer auth must not borrow the valid browser session.
    assert (
        local_client.get("/api/v1/me", headers={"Authorization": "Bearer invalid"}).status_code
        == 401
    )
    assert (
        local_client.get(
            "/api/v1/workspaces", headers={"Authorization": "Bearer pca_invalid"}
        ).status_code
        == 401
    )
    assert "HttpOnly" in login.headers["set-cookie"]
    assert "SameSite=lax" in login.headers["set-cookie"]
    if cast(FastAPI, local_client.app).state.settings.app_env is not Environment.LOCAL:
        assert "Secure" in login.headers["set-cookie"]
    assert local_client.get("/auth/config").json() == {
        "mode": AuthMode.LOCAL.value,
        "social_providers": [],
        "registration_mode": "closed",
    }

    projects = local_client.get("/api/v1/workspaces?scope=member")
    assert projects.status_code == 200
    assert projects.json()["items"] == []


def test_setup_route_is_removed_and_logout_revokes_session(local_client: TestClient) -> None:
    assert local_client.post("/auth/setup", json={}).status_code == 404
    assert (
        local_client.post(
            "/auth/login", json={"username": "admin", "password": "correct horse battery staple"}
        ).status_code
        == 200
    )
    logout = local_client.post("/auth/logout")
    assert logout.status_code == 204
    assert local_client.get("/api/v1/workspaces?scope=member").status_code == 401


def test_local_login_rejects_wrong_password_and_accepts_correct_password(
    local_client: TestClient,
) -> None:
    wrong = local_client.post(
        "/auth/login", json={"username": "admin", "password": "wrong password"}
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "http_error"

    login = local_client.post(
        "/auth/login", json={"username": "admin", "password": "correct horse battery staple"}
    )
    assert login.status_code == 200
    assert local_client.get("/api/v1/workspaces?scope=member").status_code == 200


def test_local_login_rate_limits_before_additional_password_hashing(
    local_client: TestClient,
) -> None:
    app = cast(FastAPI, local_client.app)
    app.state.settings.login_address_requests_per_minute = 2
    for _ in range(2):
        assert (
            local_client.post(
                "/auth/login", json={"username": "admin", "password": "wrong password"}
            ).status_code
            == 401
        )
    limited = local_client.post(
        "/auth/login", json={"username": "admin", "password": "wrong password"}
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "login_rate_limited"
    assert limited.headers["retry-after"]


def test_unknown_and_invalid_usernames_use_dummy_password_verification(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[str | None] = []

    def reject(_: str, encoded: str | None) -> bool:
        observed.append(encoded)
        return False

    monkeypatch.setattr("polycolab.accounts.builtin.verify_password", reject)
    for username in ("missing-user", "not valid!"):
        response = local_client.post(
            "/auth/login", json={"username": username, "password": "wrong password"}
        )
        assert response.status_code == 401
    assert len(observed) == 2
    assert all(digest is not None and digest.startswith("scrypt$") for digest in observed)


def test_local_login_rate_limits_normalized_username(local_client: TestClient) -> None:
    app = cast(FastAPI, local_client.app)
    app.state.settings.login_username_requests_per_minute = 1
    assert (
        local_client.post(
            "/auth/login", json={"username": "Missing.User", "password": "wrong password"}
        ).status_code
        == 401
    )
    limited = local_client.post(
        "/auth/login", json={"username": " missing.user ", "password": "wrong password"}
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "login_rate_limited"


def test_local_login_validation_is_enforced(local_client: TestClient) -> None:
    response = local_client.post("/auth/login", json={"username": "admin", "password": ""})
    assert response.status_code == 422
