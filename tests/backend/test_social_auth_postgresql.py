"""Real PostgreSQL replay, identity-race, and immutable-audit evidence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, local
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

import polycolab.accounts.social as social_auth
from polycolab.accounts.builtin import create_account, create_session, token_digest
from polycolab.accounts.social import (
    ConsumedSocialFlow,
    SocialAuthConflict,
    SocialAuthInvalid,
    consume_social_flow,
    create_social_flow,
    link_social_identity,
    purge_expired_social_transactions,
    resolve_social_sign_in,
    unlink_social_identity,
)
from polycolab.db.models import (
    SqlAuthSession,
    SqlLocalAccount,
    SqlSocialAccountIdentity,
    SqlSocialIdentityAudit,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import (
    SocialAuthPurpose,
    SocialIdentityAuditAction,
    SocialProviderKind,
)
from polycolab.entities.time import utc_now


def _seed_admin(engine: Engine) -> None:
    with Session(engine) as session:
        create_account(
            SqlAlchemyTransaction(session),
            username="admin",
            password="correct horse battery staple",
            display_name=None,
            is_admin=True,
        )
        session.commit()


def test_postgresql_social_flow_is_single_use_under_contention(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    _seed_admin(engine)
    with Session(engine) as session:
        flow = create_social_flow(
            session,
            provider=SocialProviderKind.GOOGLE,
            purpose=SocialAuthPurpose.SIGN_IN,
            return_path="/",
            ttl_seconds=300,
        )
    barrier = Barrier(2)

    def consume() -> ConsumedSocialFlow | type[SocialAuthInvalid]:
        barrier.wait(timeout=10)
        with Session(engine) as session:
            try:
                return consume_social_flow(
                    session,
                    provider=SocialProviderKind.GOOGLE,
                    state=flow.state,
                    browser_binding=flow.browser_binding,
                    session_token=None,
                    reauthentication_seconds=300,
                )
            except SocialAuthInvalid:
                return SocialAuthInvalid

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: consume(), range(2)))
    assert sum(isinstance(outcome, ConsumedSocialFlow) for outcome in outcomes) == 1
    assert outcomes.count(SocialAuthInvalid) == 1
    with Session(engine) as session:
        create_social_flow(
            session,
            provider=SocialProviderKind.GITHUB,
            purpose=SocialAuthPurpose.SIGN_IN,
            return_path="/",
            ttl_seconds=300,
            now=utc_now() - timedelta(minutes=10),
        )
        assert purge_expired_social_transactions(session) == 1


def test_postgresql_concurrent_first_sign_in_creates_one_account_and_audit(
    pg_schema: tuple[Engine, Config, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    _seed_admin(engine)
    flow = ConsumedSocialFlow(
        transaction_id=uuid4(),
        provider=SocialProviderKind.GITHUB,
        purpose=SocialAuthPurpose.SIGN_IN,
        pkce_verifier="v" * 64,
        nonce="n" * 32,
        return_path="/",
        linked_account_id=None,
        linked_session_id=None,
        current_account_id=None,
    )
    barrier = Barrier(2)
    thread_state = local()
    original_identity = social_auth._identity

    def synchronized_identity(
        session: Session, provider: SocialProviderKind, subject: str
    ) -> SqlSocialAccountIdentity | None:
        identity = original_identity(session, provider, subject)
        if not getattr(thread_state, "synchronized", False):
            thread_state.synchronized = True
            barrier.wait(timeout=10)
        return identity

    monkeypatch.setattr(social_auth, "_identity", synchronized_identity)

    def resolve() -> object:
        with Session(engine, expire_on_commit=False) as session:
            return resolve_social_sign_in(
                session,
                flow=flow,
                subject="424242",
                display_name="Mutable provider display",
            ).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        account_ids = list(pool.map(lambda _: resolve(), range(2)))
    assert account_ids[0] == account_ids[1]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SqlLocalAccount)) == 2
        assert session.scalar(select(func.count()).select_from(SqlSocialAccountIdentity)) == 1
        assert session.scalar(select(func.count()).select_from(SqlSocialIdentityAudit)) == 1


def test_postgresql_identity_binding_and_audit_are_immutable(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    _seed_admin(engine)
    flow = ConsumedSocialFlow(
        transaction_id=uuid4(),
        provider=SocialProviderKind.GOOGLE,
        purpose=SocialAuthPurpose.SIGN_IN,
        pkce_verifier="v" * 64,
        nonce="n" * 32,
        return_path="/",
        linked_account_id=None,
        linked_session_id=None,
        current_account_id=None,
    )
    with Session(engine) as session:
        resolve_social_sign_in(session, flow=flow, subject="stable-subject", display_name=None)
        identity = session.scalar(select(SqlSocialAccountIdentity))
        audit = session.scalar(select(SqlSocialIdentityAudit))
        assert identity is not None and audit is not None
        identity.subject = "replacement-subject"
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()
        audit = session.get(SqlSocialIdentityAudit, audit.id)
        assert audit is not None
        audit.created_at = utc_now() + timedelta(seconds=1)
        with pytest.raises(DBAPIError):
            session.commit()


def test_postgresql_concurrent_link_conflict_has_one_winner(
    pg_schema: tuple[Engine, Config, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    with Session(engine, expire_on_commit=False) as session:
        alice = create_account(
            SqlAlchemyTransaction(session),
            username="alice",
            password="correct horse battery staple",
            display_name=None,
        )
        bob = create_account(
            SqlAlchemyTransaction(session),
            username="bob",
            password="another correct password",
            display_name=None,
        )
        session.commit()
        alice_token = create_session(
            SqlAlchemyTransaction(session), account_id=alice.id, ttl_seconds=3600
        )
        bob_token = create_session(
            SqlAlchemyTransaction(session), account_id=bob.id, ttl_seconds=3600
        )
        rows = {
            row.account_id: row.id
            for row in session.scalars(
                select(SqlAuthSession).where(
                    SqlAuthSession.token_digest.in_(
                        (token_digest(alice_token), token_digest(bob_token))
                    )
                )
            )
        }
        account_sessions = (
            (alice.id, rows[alice.id], alice_token),
            (bob.id, rows[bob.id], bob_token),
        )
    barrier = Barrier(2)
    thread_state = local()
    original_identity = social_auth._identity

    def synchronized_identity(
        session: Session, provider: SocialProviderKind, subject: str
    ) -> SqlSocialAccountIdentity | None:
        identity = original_identity(session, provider, subject)
        if not getattr(thread_state, "synchronized", False):
            thread_state.synchronized = True
            barrier.wait(timeout=10)
        return identity

    monkeypatch.setattr(social_auth, "_identity", synchronized_identity)

    def link(binding: tuple[UUID, UUID, str]) -> object:
        account_id, auth_session_id, token = binding
        flow = ConsumedSocialFlow(
            transaction_id=uuid4(),
            provider=SocialProviderKind.GOOGLE,
            purpose=SocialAuthPurpose.LINK,
            pkce_verifier="v" * 64,
            nonce="n" * 32,
            return_path="/",
            linked_account_id=account_id,
            linked_session_id=auth_session_id,
            current_account_id=account_id,
        )
        with Session(engine) as session:
            try:
                return link_social_identity(
                    session,
                    flow=flow,
                    subject="one-provider-identity",
                    session_token=token,
                    reauthentication_seconds=300,
                ).id
            except SocialAuthConflict:
                return SocialAuthConflict

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(link, account_sessions))
    assert sum(outcome is SocialAuthConflict for outcome in outcomes) == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SqlSocialAccountIdentity)) == 1
        assert session.scalar(select(func.count()).select_from(SqlSocialIdentityAudit)) == 1


def test_postgresql_concurrent_unlink_preserves_one_login_method(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    with Session(engine, expire_on_commit=False) as session:
        account = SqlLocalAccount(
            username="social-only",
            password_digest=None,
            display_name=None,
            is_admin=False,
        )
        session.add(account)
        session.flush()
        identities = [
            SqlSocialAccountIdentity(
                account_id=account.id,
                provider=provider,
                subject=subject,
            )
            for provider, subject in (
                (SocialProviderKind.GOOGLE, "google-subject"),
                (SocialProviderKind.GITHUB, "42"),
            )
        ]
        session.add_all(identities)
        session.flush()
        session.add_all(
            SqlSocialIdentityAudit(
                identity_id=identity.id,
                account_id=account.id,
                actor_account_id=None,
                action=SocialIdentityAuditAction.CREATED,
            )
            for identity in identities
        )
        session.commit()
        tokens = (
            create_session(SqlAlchemyTransaction(session), account_id=account.id, ttl_seconds=3600),
            create_session(SqlAlchemyTransaction(session), account_id=account.id, ttl_seconds=3600),
        )
    barrier = Barrier(2)

    def unlink(binding: tuple[SocialProviderKind, str]) -> type[SocialAuthConflict] | None:
        provider, token = binding
        barrier.wait(timeout=10)
        with Session(engine) as session:
            try:
                unlink_social_identity(
                    session,
                    provider=provider,
                    session_token=token,
                    reauthentication_seconds=300,
                )
                return None
            except SocialAuthConflict:
                return SocialAuthConflict

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                unlink,
                (
                    (SocialProviderKind.GOOGLE, tokens[0]),
                    (SocialProviderKind.GITHUB, tokens[1]),
                ),
            )
        )
    assert outcomes.count(None) == 1
    assert outcomes.count(SocialAuthConflict) == 1
    with Session(engine) as session:
        active = session.scalar(
            select(func.count())
            .select_from(SqlSocialAccountIdentity)
            .where(SqlSocialAccountIdentity.unlinked_at.is_(None))
        )
        assert active == 1
