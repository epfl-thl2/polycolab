"""Built-in social sign-in state, account mapping, and browser-session policy."""

from __future__ import annotations

from collections.abc import Generator
from datetime import timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import AnyUrl, SecretStr, ValidationError
from sqlalchemy import func, select

from polycolab.accounts.builtin import bootstrap_admin, create_account
from polycolab.accounts.providers import SocialAuthenticationFailed, SocialIdentity
from polycolab.app.application import create_app
from polycolab.db.base import Base
from polycolab.db.models import (
    SqlAuthSession,
    SqlLocalAccount,
    SqlSocialAccountIdentity,
    SqlSocialAuthTransaction,
    SqlSocialIdentityAudit,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import SocialProviderKind
from polycolab.entities.time import utc_now
from polycolab.platform.config import AuthMode, Environment, Settings

ORIGIN = "https://app.example"


class FakeProvider:
    def __init__(self, provider: str, subject: str) -> None:
        self.provider = provider
        self.subject = subject
        self.exchange_calls = 0
        self.fail = False

    def authorization_url(self, *, state: str, verifier: str, nonce: str) -> str:
        assert len(verifier) >= 43 and len(nonce) >= 32
        return f"https://{self.provider}.example/authorize?state={state}"

    def exchange(self, *, code: str, verifier: str, nonce: str) -> SocialIdentity:
        self.exchange_calls += 1
        if self.fail:
            raise SocialAuthenticationFailed("social_authentication_failed")
        assert code == "provider-code" and len(verifier) >= 43 and len(nonce) >= 32
        return SocialIdentity(
            cast(Any, self.provider), self.subject, f"{self.provider.title()} User"
        )


@pytest.fixture
def social_client() -> Generator[TestClient]:
    settings = Settings(
        app_env=Environment.LOCAL,
        auth_mode=AuthMode.LOCAL,
        database_url="sqlite+pysqlite:///:memory:",
        public_app_origin=AnyUrl(ORIGIN),
        social_google_client_id="google-client",
        social_google_client_secret=SecretStr("google-secret"),
        social_github_client_id="github-client",
        social_github_client_secret=SecretStr("github-secret"),
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as session:
        bootstrap_admin(SqlAlchemyTransaction(session), "correct horse battery staple")
    app.state.social_providers = {
        SocialProviderKind.GOOGLE: FakeProvider("google", "google-subject"),
        SocialProviderKind.GITHUB: FakeProvider("github", "42"),
    }
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        yield client
    Base.metadata.drop_all(app.state.engine)
    app.state.engine.dispose()


def _app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


def _setup(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200, response.text


def _start(client: TestClient, provider: str, path: str = "/", *, link: bool = False) -> str:
    suffix = "/link/start" if link else "/start"
    response = client.post(
        f"/auth/social/{provider}{suffix}",
        headers={"Origin": ORIGIN},
        json={"return_path": path},
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    return cast(
        str,
        parse_qs(urlsplit(response.json()["authorization_url"]).query)["state"][0],
    )


def _callback(client: TestClient, provider: str, state: str, **query: str) -> Any:
    return client.get(
        f"/auth/social/{provider}/callback",
        params={"state": state, "code": "provider-code", **query},
    )


def test_configuration_is_complete_exact_and_secret_free(social_client: TestClient) -> None:
    assert social_client.get("/auth/config").json() == {
        "mode": "local",
        "social_providers": ["google", "github"],
        "registration_mode": "closed",
    }
    assert "secret" not in social_client.get("/auth/config").text
    for values in (
        {"social_google_client_id": "partial"},
        {
            "social_google_client_id": "client",
            "social_google_client_secret": "secret",
        },
        {
            "app_env": "production",
            "database_url": "postgresql+psycopg://db/prod",
            "kms_provider": "aws",
            "kms_key_id": "key",
            "admission_scope_hmac_key": "admission",
            "runtime_worker_token": "worker",
            "social_google_client_id": "client",
            "social_google_client_secret": "secret",
            "public_app_origin": "http://app.example",
        },
    ):
        with pytest.raises(ValidationError):
            Settings.model_validate(values)


def test_social_start_requires_same_origin_and_safe_return(
    social_client: TestClient,
) -> None:
    _setup(social_client)
    assert social_client.post("/auth/social/google/start", json={}).status_code == 403
    assert (
        social_client.post(
            "/auth/social/google/start",
            headers={"Origin": "https://attacker.example"},
            json={},
        ).status_code
        == 403
    )
    assert (
        social_client.post(
            "/auth/social/google/start",
            headers={"Origin": ORIGIN},
            json={"return_path": "https://attacker.example"},
        ).status_code
        == 422
    )


@pytest.mark.parametrize("provider", ["google", "github"])
def test_social_callback_creates_non_admin_passwordless_account(
    social_client: TestClient, provider: str
) -> None:
    _setup(social_client)
    social_client.post("/auth/logout")
    state = _start(social_client, provider, "/projects")
    app = _app(social_client)
    with app.state.session_factory() as session:
        transaction = session.scalar(select(SqlSocialAuthTransaction))
        assert transaction is not None
        assert transaction.state_digest != state
        assert state not in repr(transaction)
        assert "polycolab_social_flow" in social_client.cookies

    callback = _callback(social_client, provider, state)
    assert callback.status_code == 303
    assert callback.headers["location"] == "/projects?social_auth=success"
    assert callback.headers["cache-control"] == "no-store"
    current = social_client.get("/auth/me").json()
    assert current["authenticated"] is True and current["is_admin"] is False
    assert current["username"].startswith(f"social-{provider}-")

    with app.state.session_factory() as session:
        account = session.scalar(
            select(SqlLocalAccount).where(SqlLocalAccount.username == current["username"])
        )
        assert account is not None and account.password_digest is None
        mapping = session.scalar(
            select(SqlSocialAccountIdentity).where(
                SqlSocialAccountIdentity.account_id == account.id
            )
        )
        assert mapping is not None and mapping.provider.value == provider
        assert session.scalar(select(func.count()).select_from(SqlSocialIdentityAudit)) == 1
        assert session.scalar(select(func.count()).select_from(SqlSocialAuthTransaction)) == 0

    social_client.post("/auth/logout")
    assert (
        social_client.post(
            "/auth/login",
            json={"username": current["username"], "password": "any password value"},
        ).status_code
        == 401
    )


def test_wrong_browser_provider_denial_and_replay_issue_no_session(
    social_client: TestClient,
) -> None:
    _setup(social_client)
    social_client.post("/auth/logout")
    state = _start(social_client, "google")
    binding = social_client.cookies.get("polycolab_social_flow")
    assert binding

    stranger = TestClient(_app(social_client), base_url=ORIGIN, follow_redirects=False)
    assert _callback(stranger, "google", state).headers["location"] == "/?social_auth=failed"
    social_client.cookies.set("polycolab_social_flow", binding, path="/auth/social")
    assert _callback(social_client, "github", state).headers["location"] == "/?social_auth=failed"
    social_client.cookies.set("polycolab_social_flow", binding, path="/auth/social")
    success = _callback(social_client, "google", state)
    assert success.headers["location"] == "/?social_auth=success"
    social_client.cookies.set("polycolab_social_flow", binding, path="/auth/social")
    replay = _callback(social_client, "google", state)
    assert replay.headers["location"] == "/?social_auth=failed"

    social_client.post("/auth/logout")
    denied_state = _start(social_client, "google")
    denied = _callback(social_client, "google", denied_state, error="access_denied")
    assert denied.headers["location"] == "/?social_auth=failed"
    assert _app(social_client).state.social_providers[SocialProviderKind.GOOGLE].exchange_calls == 1
    assert social_client.get("/auth/me").json()["authenticated"] is False


def test_missing_or_malformed_state_clears_flow_cookie(social_client: TestClient) -> None:
    _setup(social_client)
    social_client.post("/auth/logout")
    _start(social_client, "google")
    response = social_client.get("/auth/social/google/callback", params={"code": "code"})
    assert response.status_code == 303
    assert response.headers["location"] == "/?social_auth=failed"
    assert "polycolab_social_flow" not in social_client.cookies

    _start(social_client, "google")
    response = social_client.get(
        "/auth/social/google/callback", params={"state": "short", "code": "code"}
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?social_auth=failed"
    assert "polycolab_social_flow" not in social_client.cookies


def test_expired_or_failed_provider_flow_issues_no_session(social_client: TestClient) -> None:
    _setup(social_client)
    social_client.post("/auth/logout")
    expired_state = _start(social_client, "google")
    with _app(social_client).state.session_factory() as session:
        transaction = session.scalar(select(SqlSocialAuthTransaction))
        assert transaction is not None
        transaction.created_at = utc_now() - timedelta(minutes=10)
        transaction.expires_at = utc_now() - timedelta(seconds=1)
        session.commit()
    expired = _callback(social_client, "google", expired_state)
    assert expired.headers["location"] == "/?social_auth=failed"

    failed_state = _start(social_client, "google")
    adapter = _app(social_client).state.social_providers[SocialProviderKind.GOOGLE]
    adapter.fail = True
    failed = _callback(social_client, "google", failed_state)
    assert failed.headers["location"] == "/?social_auth=failed"
    assert social_client.get("/auth/me").json()["authenticated"] is False
    with _app(social_client).state.session_factory() as session:
        # The next start purges the expired row; consumed provider failures are
        # removed and cannot be retried.
        assert session.scalar(select(func.count()).select_from(SqlSocialAuthTransaction)) == 0


def test_social_routes_are_disabled_outside_local_auth() -> None:
    settings = Settings(
        app_env=Environment.LOCAL,
        auth_mode=AuthMode.OIDC,
        database_url="sqlite+pysqlite:///:memory:",
        public_app_origin=AnyUrl(ORIGIN),
        social_google_client_id="google-client",
        social_google_client_secret=SecretStr("google-secret"),
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    try:
        with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
            configuration = client.get("/auth/config").json()
            assert configuration["mode"] == AuthMode.OIDC.value
            assert "social_providers" not in configuration
            assert (
                client.post(
                    "/auth/social/google/start",
                    headers={"Origin": ORIGIN},
                    json={},
                ).status_code
                == 404
            )
    finally:
        Base.metadata.drop_all(app.state.engine)
        app.state.engine.dispose()


def test_sign_in_never_email_or_display_name_links_existing_account(
    social_client: TestClient,
) -> None:
    _setup(social_client)
    social_client.post("/auth/logout")
    state = _start(social_client, "google")
    assert _callback(social_client, "google", state).headers["location"].endswith("success")
    with _app(social_client).state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(SqlLocalAccount)) == 2


def test_link_rechecks_recent_exact_session_and_identity_conflicts(
    social_client: TestClient,
) -> None:
    _setup(social_client)
    state = _start(social_client, "google", "/account", link=True)
    social_client.post("/auth/logout")
    assert _callback(social_client, "google", state).headers["location"].endswith("failed")

    login = social_client.post(
        "/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    state = _start(social_client, "google", "/account", link=True)
    linked = _callback(social_client, "google", state)
    assert linked.headers["location"] == "/account?social_auth=success"
    identities = social_client.get("/auth/social/identities").json()
    assert identities == {
        "configured": ["google", "github"],
        "linked": ["google"],
        "password_enabled": True,
    }

    app = _app(social_client)
    with app.state.session_factory() as session:
        bob = create_account(
            SqlAlchemyTransaction(session),
            username="bob",
            password="another correct password",
            display_name=None,
        )
        session.commit()
        assert bob.id is not None
    social_client.post("/auth/logout")
    social_client.post(
        "/auth/login", json={"username": "bob", "password": "another correct password"}
    )
    state = _start(social_client, "google", "/account", link=True)
    assert _callback(social_client, "google", state).headers["location"].endswith("failed")


def test_link_requires_recent_reauthentication_and_unlink_preserves_login(
    social_client: TestClient,
) -> None:
    _setup(social_client)
    app = _app(social_client)
    with app.state.session_factory() as session:
        auth_session = session.scalar(
            select(SqlAuthSession).where(SqlAuthSession.revoked_at.is_(None))
        )
        assert auth_session is not None
        auth_session.reauthenticated_at = utc_now() - timedelta(hours=1)
        session.commit()
    assert (
        social_client.post(
            "/auth/social/google/link/start",
            headers={"Origin": ORIGIN},
            json={},
        ).status_code
        == 401
    )
    assert (
        social_client.post(
            "/auth/reauthenticate",
            headers={"Origin": ORIGIN},
            json={"password": "wrong password"},
        ).status_code
        == 401
    )
    assert social_client.post(
        "/auth/reauthenticate",
        headers={"Origin": ORIGIN},
        json={"password": "correct horse battery staple"},
    ).json() == {"reauthenticated": True}
    state = _start(social_client, "google", link=True)
    assert _callback(social_client, "google", state).headers["location"].endswith("success")
    unlinked = social_client.post("/auth/social/google/unlink", headers={"Origin": ORIGIN})
    assert unlinked.status_code == 204
    assert social_client.get("/auth/social/identities").json()["linked"] == []


def test_social_only_account_cannot_unlink_its_last_method(social_client: TestClient) -> None:
    _setup(social_client)
    social_client.post("/auth/logout")
    state = _start(social_client, "google")
    _callback(social_client, "google", state)
    response = social_client.post("/auth/social/google/unlink", headers={"Origin": ORIGIN})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "http_error"
