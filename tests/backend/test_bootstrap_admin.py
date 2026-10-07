from __future__ import annotations

import pytest
from pydantic import AnyUrl, SecretStr
from sqlalchemy import select

from polycolab.accounts.builtin import authenticate_account, bootstrap_admin
from polycolab.db.base import Base
from polycolab.db.models import SqlLocalAccount
from polycolab.db.session import make_engine, make_session_factory
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.operations.bootstrap_admin import run
from polycolab.platform.config import AuthMode, Settings


def test_bootstrap_creates_fixed_admin_once_without_resetting_password() -> None:
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    try:
        with factory() as session:
            transaction = SqlAlchemyTransaction(session)
            assert bootstrap_admin(transaction, "correct horse battery staple") is True
            assert bootstrap_admin(transaction, "a different valid bootstrap password") is False
            account = authenticate_account(
                transaction, username="admin", password="correct horse battery staple"
            )
            assert account.is_admin is True
            assert account.display_name == "Admin"
            assert session.scalar(select(SqlLocalAccount.password_digest)) != (
                "correct horse battery staple"
            )
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_bootstrap_requires_password_only_for_empty_local_database() -> None:
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    try:
        with factory() as session, pytest.raises(ValueError, match="BOOTSTRAP_ADMIN_PASSWORD"):
            bootstrap_admin(SqlAlchemyTransaction(session), None)
        with factory() as session:
            bootstrap_admin(SqlAlchemyTransaction(session), "correct horse battery staple")
        with factory() as session:
            assert bootstrap_admin(SqlAlchemyTransaction(session), None) is False
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_bootstrap_command_is_noop_for_oidc() -> None:
    settings = Settings(
        auth_mode=AuthMode.OIDC,
        oidc_issuer=AnyUrl("https://issuer.example"),
        oidc_jwks_url=AnyUrl("https://issuer.example/keys"),
        bootstrap_admin_password=SecretStr("ignored bootstrap password"),
    )
    assert run(settings) is False
