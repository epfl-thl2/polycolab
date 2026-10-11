"""Real PostgreSQL registration atomicity and contention evidence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import AnyUrl
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import polycolab.accounts.builtin as local_accounts
from polycolab.accounts.builtin import (
    AccountAlreadyExists,
    RegistrationInvitationInvalid,
    bootstrap_admin,
    create_account,
    issue_registration_invitation,
    register_account,
    revoke_registration_invitation,
)
from polycolab.app.application import create_app
from polycolab.db.models import (
    SqlAuthSession,
    SqlExecutionRateWindow,
    SqlLocalAccount,
    SqlMembership,
    SqlRegistrationInvitation,
    SqlUser,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import InvitationStatus
from polycolab.execution.limits import ExecutionLimitExceeded, enforce_login_address_limit
from polycolab.platform.config import RegistrationMode, Settings

PASSWORD = "correct horse battery staple"


def _seed_admin(engine: Engine) -> None:
    with Session(engine) as session:
        create_account(
            SqlAlchemyTransaction(session),
            username="admin",
            password=PASSWORD,
            display_name=None,
            is_admin=True,
        )
        session.commit()


def test_postgresql_bootstrap_and_login_admission_serialize_first_writers(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    bootstrap_barrier = Barrier(2)

    def initialize() -> bool:
        with Session(engine) as session:
            bootstrap_barrier.wait()
            return bootstrap_admin(SqlAlchemyTransaction(session), PASSWORD)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: initialize(), range(2))) == [False, True]

    admission_barrier = Barrier(2)
    now = datetime(2026, 9, 14, 12, tzinfo=UTC)

    def admit() -> bool:
        with Session(engine) as session:
            admission_barrier.wait()
            try:
                enforce_login_address_limit(
                    session,
                    client_address="192.0.2.10",
                    hmac_key="test-admission-key",
                    limit=1,
                    now=now,
                )
                session.commit()
                return True
            except ExecutionLimitExceeded:
                session.rollback()
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: admit(), range(2))) == [False, True]
    with Session(engine) as session:
        row = session.scalar(
            select(SqlExecutionRateWindow).where(SqlExecutionRateWindow.scope == "login_ip")
        )
        assert row is not None and row.count == 1


def test_postgresql_registration_runs_through_real_api_boundary(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(
            database_url=url,
            web_dist_dir="/missing-registration-web",
            public_app_origin=AnyUrl("https://registration.example"),
            registration_mode=RegistrationMode.OPEN,
            registration_requests_per_minute=100,
        )
    )
    try:
        with TestClient(app, base_url="https://registration.example") as client:
            _seed_admin(engine)
            assert (
                client.post(
                    "/auth/login", json={"username": "admin", "password": PASSWORD}
                ).status_code
                == 200
            )
            client.post("/auth/logout")
            registered = client.post(
                "/auth/register",
                headers={"Origin": "https://registration.example"},
                json={"username": "api-user", "password": PASSWORD},
            )
            assert registered.status_code == 201
            assert registered.json()["is_admin"] is False
            assert client.get("/api/v1/workspaces").status_code == 200
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(SqlLocalAccount)) == 2
            assert session.scalar(select(func.count()).select_from(SqlAuthSession)) == 2
    finally:
        app.state.engine.dispose()


def test_postgresql_exact_username_membership_materializes_registered_user_atomically(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(Settings(database_url=url, web_dist_dir="/missing-membership-web"))
    try:
        with TestClient(app, base_url="https://testserver") as client:
            _seed_admin(engine)
            assert (
                client.post(
                    "/auth/login", json={"username": "admin", "password": PASSWORD}
                ).status_code
                == 200
            )
            project = client.post(
                "/api/v1/workspaces",
                json={"name": "Research research", "visibility": "PRIVATE"},
            )
            assert project.status_code == 201
            with Session(engine, expire_on_commit=False) as session:
                account = create_account(
                    SqlAlchemyTransaction(session),
                    username="research-member",
                    password=PASSWORD,
                    display_name="Research Member",
                )
                session.commit()
                assert (
                    session.scalar(
                        select(SqlUser).where(
                            SqlUser.issuer == "polycolab-local", SqlUser.subject == str(account.id)
                        )
                    )
                    is None
                )

            member = client.post(
                f"/api/v1/workspaces/{project.json()['id']}/members",
                json={"username": " RESEARCH-MEMBER ", "role": "CONTRIBUTOR"},
            )
            assert member.status_code == 201, member.text
            assert member.json()["username"] == "research-member"
            assert member.json()["display_name"] == "Research Member"
            duplicate = client.post(
                f"/api/v1/workspaces/{project.json()['id']}/members",
                json={"username": "research-member", "role": "READ_ONLY"},
            )
            assert duplicate.status_code == 409

        with Session(engine) as session:
            canonical = session.scalar(
                select(SqlUser).where(
                    SqlUser.issuer == "polycolab-local", SqlUser.subject == str(account.id)
                )
            )
            assert canonical is not None
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(SqlMembership)
                    .where(SqlMembership.user_id == canonical.id)
                )
                == 1
            )
    finally:
        app.state.engine.dispose()


def test_postgresql_concurrent_username_registration_has_one_complete_winner(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    _seed_admin(engine)
    barrier = Barrier(2)

    def register() -> str:
        barrier.wait(timeout=10)
        with Session(engine) as session:
            try:
                register_account(
                    SqlAlchemyTransaction(session),
                    username="same-user",
                    password=PASSWORD,
                    display_name=None,
                    invitation_code=None,
                    session_ttl_seconds=3600,
                )
                return "created"
            except AccountAlreadyExists:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: register(), range(2)))
    assert sorted(outcomes) == ["conflict", "created"]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SqlLocalAccount)) == 2
        assert session.scalar(select(func.count()).select_from(SqlAuthSession)) == 1


def test_postgresql_invitation_is_consumed_once_under_contention(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    _seed_admin(engine)
    with Session(engine, expire_on_commit=False) as session:
        admin = session.scalar(select(SqlLocalAccount).where(SqlLocalAccount.is_admin.is_(True)))
        assert admin is not None
        code = issue_registration_invitation(
            SqlAlchemyTransaction(session), created_by_account_id=admin.id, ttl_seconds=3600
        ).code
    barrier = Barrier(2)

    def register(index: int) -> str:
        barrier.wait(timeout=10)
        with Session(engine) as session:
            try:
                register_account(
                    SqlAlchemyTransaction(session),
                    username=f"invite-user-{index}",
                    password=PASSWORD,
                    display_name=None,
                    invitation_code=code,
                    session_ttl_seconds=3600,
                )
                return "created"
            except RegistrationInvitationInvalid:
                return "invalid"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(register, range(2)))
    assert sorted(outcomes) == ["created", "invalid"]
    with Session(engine) as session:
        invitation = session.scalar(select(SqlRegistrationInvitation))
        assert invitation is not None
        assert invitation.status is InvitationStatus.ACCEPTED
        assert invitation.accepted_by_account_id is not None
        assert session.scalar(select(func.count()).select_from(SqlLocalAccount)) == 2
        assert session.scalar(select(func.count()).select_from(SqlAuthSession)) == 1


def test_postgresql_registration_rolls_back_account_if_session_creation_fails(
    pg_schema: tuple[Engine, Config, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    _seed_admin(engine)

    def fail_session(*args: object, **kwargs: object) -> str:
        raise RuntimeError("injected session failure")

    monkeypatch.setattr(local_accounts, "prepare_session", fail_session)
    with Session(engine) as session:
        with pytest.raises(RuntimeError, match="injected session failure"):
            register_account(
                SqlAlchemyTransaction(session),
                username="rolled-back",
                password=PASSWORD,
                display_name=None,
                invitation_code=None,
                session_ttl_seconds=3600,
            )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SqlLocalAccount)) == 1
        assert session.scalar(select(func.count()).select_from(SqlAuthSession)) == 0


def test_postgresql_revoked_invitation_cannot_register(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    _seed_admin(engine)
    with Session(engine, expire_on_commit=False) as session:
        admin = session.scalar(select(SqlLocalAccount).where(SqlLocalAccount.is_admin.is_(True)))
        assert admin is not None
        issued = issue_registration_invitation(
            SqlAlchemyTransaction(session), created_by_account_id=admin.id, ttl_seconds=3600
        )
        invitation_id = issued.invitation.id
        code = issued.code
        revoke_registration_invitation(SqlAlchemyTransaction(session), invitation_id)
    with Session(engine) as session:
        with pytest.raises(RegistrationInvitationInvalid):
            register_account(
                SqlAlchemyTransaction(session),
                username="revoked-user",
                password=PASSWORD,
                display_name=None,
                invitation_code=code,
                session_ttl_seconds=3600,
            )
        assert session.scalar(select(func.count()).select_from(SqlLocalAccount)) == 1
