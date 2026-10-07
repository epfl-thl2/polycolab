from __future__ import annotations

import base64
from collections.abc import Generator
from datetime import timedelta
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import AnyUrl
from sqlalchemy import select

from polycolab.accounts.builtin import bootstrap_admin, create_account
from polycolab.accounts.recovery import (
    MailClaimInvalid,
    claim_mail,
    decrypt_claimed_mail,
    finish_mail_claim,
)
from polycolab.app.application import create_app
from polycolab.db.base import Base
from polycolab.db.models import (
    SqlAccountEmail,
    SqlAccountRecoveryToken,
    SqlAuthSession,
    SqlMailOutbox,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import MailOutboxStatus
from polycolab.entities.time import utc_now
from polycolab.platform.config import Settings

ORIGIN = "https://recovery.example"
PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a different correct password"
ORIGIN_HEADER = {"Origin": ORIGIN}


@pytest.fixture
def recovery_client(tmp_path: Path) -> Generator[TestClient]:
    key = base64.urlsafe_b64encode(b"r" * 32).decode("ascii")
    app = create_app(
        Settings(
            database_url="sqlite+pysqlite:///:memory:",
            web_dist_dir=str(tmp_path / "missing-web"),
            public_app_origin=AnyUrl(ORIGIN),
            local_credential_master_key=key,
        )
    )
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as session:
        bootstrap_admin(SqlAlchemyTransaction(session), PASSWORD)
    with TestClient(app, base_url=ORIGIN) as client:
        yield client
    Base.metadata.drop_all(app.state.engine)
    app.state.engine.dispose()


def _setup(client: TestClient) -> None:
    response = client.post("/auth/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 200


def _claim_token(client: TestClient, purpose: str) -> tuple[str, SqlMailOutbox]:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        rows = claim_mail(
            session,
            worker_id="test-dispatcher",
            limit=10,
            lease_seconds=60,
            max_attempts=8,
        )
        row = next(item for item in rows if item.purpose.value == purpose)
        payload = decrypt_claimed_mail(row, app.state.credential_wrapper)
        token = parse_qs(urlparse(payload.action_url).query)["token"][0]
        session.expunge(row)
        return token, row


def test_optional_email_verification_replacement_and_reset_revoke_sessions(
    recovery_client: TestClient,
) -> None:
    _setup(recovery_client)
    empty = recovery_client.get("/api/v1/account/email")
    assert empty.status_code == 200
    assert empty.json()["verified_email"] is None

    requested = recovery_client.put(
        "/api/v1/account/email",
        headers=ORIGIN_HEADER,
        json={"email": " Alice@Example.Test "},
    )
    assert requested.status_code == 200, requested.text
    assert requested.json()["pending_email"] == "alice@example.test"
    assert requested.json()["verified_email"] is None

    app = cast(FastAPI, recovery_client.app)
    with app.state.session_factory() as session:
        queued = session.scalar(select(SqlMailOutbox))
        token_row = session.scalar(select(SqlAccountRecoveryToken))
        assert queued is not None and token_row is not None
        assert b"alice@example.test" not in (queued.encrypted_payload or b"")
        assert len(token_row.token_digest) == 64

    verification_token, verification_mail = _claim_token(recovery_client, "EMAIL_VERIFICATION")
    verified = recovery_client.post(
        "/api/v1/account/email/verify",
        headers=ORIGIN_HEADER,
        json={"token": verification_token},
    )
    assert verified.status_code == 200
    state = recovery_client.get("/api/v1/account/email").json()
    assert state["verified_email"] == "alice@example.test"
    assert state["pending_email"] is None
    with app.state.session_factory() as session:
        erased = session.get(SqlMailOutbox, verification_mail.id)
        assert erased is not None
        assert erased.status is MailOutboxStatus.CANCELLED
        assert erased.encrypted_payload is None and erased.wrapped_data_key is None

    replacement = recovery_client.put(
        "/api/v1/account/email",
        headers=ORIGIN_HEADER,
        json={"email": "second@example.test"},
    )
    assert replacement.status_code == 200
    assert replacement.json()["verified_email"] == "alice@example.test"
    assert replacement.json()["pending_email"] == "second@example.test"
    replacement_token, _ = _claim_token(recovery_client, "EMAIL_VERIFICATION")
    assert (
        recovery_client.post(
            "/api/v1/account/email/verify",
            headers=ORIGIN_HEADER,
            json={"token": replacement_token},
        ).status_code
        == 200
    )

    unknown = recovery_client.post(
        "/api/v1/auth/password-reset/request",
        headers=ORIGIN_HEADER,
        json={"email": "unknown@example.test"},
    )
    known = recovery_client.post(
        "/api/v1/auth/password-reset/request",
        headers=ORIGIN_HEADER,
        json={"email": "SECOND@example.test"},
    )
    assert unknown.status_code == known.status_code == 200
    assert unknown.json() == known.json() == {"accepted": True}

    reset_token, _ = _claim_token(recovery_client, "PASSWORD_RESET")
    confirmed = recovery_client.post(
        "/api/v1/auth/password-reset/confirm",
        headers=ORIGIN_HEADER,
        json={"token": reset_token, "password": NEW_PASSWORD},
    )
    assert confirmed.status_code == 200
    assert recovery_client.get("/api/v1/account/email").status_code == 401
    assert (
        recovery_client.post(
            "/api/v1/auth/password-reset/confirm",
            headers=ORIGIN_HEADER,
            json={"token": reset_token, "password": NEW_PASSWORD},
        ).status_code
        == 400
    )
    assert (
        recovery_client.post(
            "/auth/login", json={"username": "admin", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert (
        recovery_client.post(
            "/auth/login", json={"username": "admin", "password": NEW_PASSWORD}
        ).status_code
        == 200
    )


def test_email_change_requires_recent_password_reauthentication(
    recovery_client: TestClient,
) -> None:
    _setup(recovery_client)
    app = cast(FastAPI, recovery_client.app)
    with app.state.session_factory() as session:
        auth_session = session.scalar(select(SqlAuthSession))
        assert auth_session is not None
        auth_session.password_reauthenticated_at = utc_now() - timedelta(hours=1)
        session.commit()

    denied = recovery_client.put(
        "/api/v1/account/email",
        headers=ORIGIN_HEADER,
        json={"email": "alice@example.test"},
    )
    assert denied.status_code == 401
    assert (
        recovery_client.post(
            "/auth/reauthenticate", headers=ORIGIN_HEADER, json={"password": PASSWORD}
        ).status_code
        == 200
    )
    assert (
        recovery_client.put(
            "/api/v1/account/email",
            headers=ORIGIN_HEADER,
            json={"email": "alice@example.test"},
        ).status_code
        == 200
    )


def test_resend_rotates_verification_and_expired_reset_is_rejected(
    recovery_client: TestClient,
) -> None:
    _setup(recovery_client)
    assert (
        recovery_client.put(
            "/api/v1/account/email",
            headers=ORIGIN_HEADER,
            json={"email": "alice@example.test"},
        ).status_code
        == 200
    )
    old_token, old_mail = _claim_token(recovery_client, "EMAIL_VERIFICATION")
    resent = recovery_client.post("/api/v1/account/email/resend", headers=ORIGIN_HEADER)
    assert resent.status_code == 200
    assert (
        recovery_client.post(
            "/api/v1/account/email/verify",
            headers=ORIGIN_HEADER,
            json={"token": old_token},
        ).status_code
        == 400
    )
    new_token, _ = _claim_token(recovery_client, "EMAIL_VERIFICATION")
    assert new_token != old_token
    assert (
        recovery_client.post(
            "/api/v1/account/email/verify",
            headers=ORIGIN_HEADER,
            json={"token": new_token},
        ).status_code
        == 200
    )
    app = cast(FastAPI, recovery_client.app)
    with app.state.session_factory() as session:
        cancelled = session.get(SqlMailOutbox, old_mail.id)
        assert cancelled is not None and cancelled.status is MailOutboxStatus.CANCELLED
        verification_rows = list(
            session.scalars(
                select(SqlAccountRecoveryToken).where(
                    SqlAccountRecoveryToken.purpose == "EMAIL_VERIFICATION"
                )
            )
        )
        assert all(
            token.expires_at - token.created_at == timedelta(hours=24)
            for token in verification_rows
        )

    assert (
        recovery_client.post(
            "/api/v1/auth/password-reset/request",
            headers=ORIGIN_HEADER,
            json={"email": "alice@example.test"},
        ).status_code
        == 200
    )
    reset_token, reset_mail = _claim_token(recovery_client, "PASSWORD_RESET")
    with app.state.session_factory() as session:
        token = session.get(SqlAccountRecoveryToken, reset_mail.token_id)
        assert token is not None
        assert token.expires_at - token.created_at == timedelta(minutes=30)
        token.created_at = utc_now() - timedelta(hours=2)
        token.expires_at = utc_now() - timedelta(hours=1)
        session.commit()
    assert (
        recovery_client.post(
            "/api/v1/auth/password-reset/confirm",
            headers=ORIGIN_HEADER,
            json={"token": reset_token, "password": NEW_PASSWORD},
        ).status_code
        == 400
    )


def test_mail_claims_are_fenced_retried_and_erased(recovery_client: TestClient) -> None:
    _setup(recovery_client)
    assert (
        recovery_client.put(
            "/api/v1/account/email",
            headers=ORIGIN_HEADER,
            json={"email": "alice@example.test"},
        ).status_code
        == 200
    )
    app = cast(FastAPI, recovery_client.app)
    now = utc_now()
    with app.state.session_factory() as session:
        first = claim_mail(
            session,
            worker_id="worker-a",
            limit=1,
            lease_seconds=60,
            max_attempts=3,
            now=now,
        )[0]
        first_id, first_generation = first.id, first.claim_generation
    with app.state.session_factory() as session:
        with pytest.raises(MailClaimInvalid):
            finish_mail_claim(
                session,
                mail_id=first_id,
                worker_id="worker-a",
                claim_generation=first_generation + 1,
                delivered=True,
                now=now + timedelta(seconds=1),
            )
        finish_mail_claim(
            session,
            mail_id=first_id,
            worker_id="worker-a",
            claim_generation=first_generation,
            delivered=False,
            retry_after=timedelta(seconds=30),
            now=now + timedelta(seconds=1),
        )
    with app.state.session_factory() as session:
        assert (
            claim_mail(
                session,
                worker_id="worker-b",
                limit=1,
                lease_seconds=60,
                max_attempts=3,
                now=now + timedelta(seconds=15),
            )
            == []
        )
        second = claim_mail(
            session,
            worker_id="worker-b",
            limit=1,
            lease_seconds=60,
            max_attempts=3,
            now=now + timedelta(seconds=32),
        )[0]
        assert second.claim_generation == first_generation + 1
        second_generation = second.claim_generation
    with app.state.session_factory() as session:
        finish_mail_claim(
            session,
            mail_id=first_id,
            worker_id="worker-b",
            claim_generation=second_generation,
            delivered=True,
            now=now + timedelta(seconds=33),
        )
        terminal = session.get(SqlMailOutbox, first_id)
        assert terminal is not None
        assert terminal.status is MailOutboxStatus.DELIVERED
        assert terminal.encrypted_payload is None and terminal.wrapped_data_key is None


def test_recovery_rate_limit_is_durable(
    recovery_client: TestClient,
) -> None:
    _setup(recovery_client)
    app = cast(FastAPI, recovery_client.app)
    app.state.settings.account_recovery_requests_per_hour = 1
    first = recovery_client.put(
        "/api/v1/account/email",
        headers=ORIGIN_HEADER,
        json={"email": "first@example.test"},
    )
    second = recovery_client.put(
        "/api/v1/account/email",
        headers=ORIGIN_HEADER,
        json={"email": "second@example.test"},
    )
    assert first.status_code == 200
    assert second.status_code == 429
    with app.state.session_factory() as session:
        state = session.scalar(select(SqlAccountEmail))
        assert state is not None and state.pending_email == "first@example.test"
        assert len(list(session.scalars(select(SqlMailOutbox)))) == 1


def test_verified_normalized_address_is_unique(recovery_client: TestClient) -> None:
    _setup(recovery_client)
    app = cast(FastAPI, recovery_client.app)
    with app.state.session_factory() as session:
        other = create_account(
            SqlAlchemyTransaction(session),
            username="bob",
            password=PASSWORD,
            display_name="Bob",
        )
        session.flush()
        session.add(
            SqlAccountEmail(
                account_id=other.id,
                verified_email="shared@example.test",
                verified_at=utc_now(),
            )
        )
        session.commit()

    assert (
        recovery_client.put(
            "/api/v1/account/email",
            headers=ORIGIN_HEADER,
            json={"email": "SHARED@example.test"},
        ).status_code
        == 200
    )
    token, _ = _claim_token(recovery_client, "EMAIL_VERIFICATION")
    conflict = recovery_client.post(
        "/api/v1/account/email/verify",
        headers=ORIGIN_HEADER,
        json={"token": token},
    )
    assert conflict.status_code == 409
    with app.state.session_factory() as session:
        alice_state = session.scalar(
            select(SqlAccountEmail).where(SqlAccountEmail.account_id != other.id)
        )
        assert alice_state is not None
        assert alice_state.verified_email is None
        assert alice_state.pending_email == "shared@example.test"
