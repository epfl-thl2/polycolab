"""Real PostgreSQL contention evidence for Research account recovery."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from polycolab.accounts.builtin import create_account
from polycolab.accounts.recovery import (
    RecoveryConflict,
    claim_mail,
    decrypt_claimed_mail,
    request_email_change,
    verify_email,
)
from polycolab.db.models import SqlAccountEmail
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.model_gateway.credentials import LocalAesGcmKeyWrapper

PASSWORD = "correct horse battery staple"


def test_postgresql_verified_email_contention_has_one_winner(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    wrapper = LocalAesGcmKeyWrapper(AESGCM.generate_key(bit_length=256))
    account_ids: list[UUID] = []
    with Session(engine, expire_on_commit=False) as session:
        for username in ("recovery-a", "recovery-b"):
            account = create_account(
                SqlAlchemyTransaction(session),
                username=username,
                password=PASSWORD,
                display_name=username,
            )
            session.commit()
            account_ids.append(account.id)
            request_email_change(
                session,
                account=account,
                email="shared@example.test",
                public_origin="https://recovery.example",
                wrapper=wrapper,
            )

    tokens: dict[UUID, str] = {}
    with Session(engine) as session:
        for row in claim_mail(
            session,
            worker_id="test-mail",
            limit=10,
            lease_seconds=60,
            max_attempts=8,
        ):
            payload = decrypt_claimed_mail(row, wrapper)
            tokens[row.account_id] = parse_qs(urlparse(payload.action_url).query)["token"][0]

    barrier = Barrier(2)

    def verify(account_id: UUID) -> str:
        barrier.wait(timeout=10)
        with Session(engine) as session:
            try:
                verify_email(session, raw_token=tokens[account_id])
                return "verified"
            except RecoveryConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(verify, account_ids))
    assert sorted(outcomes) == ["conflict", "verified"]
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(SqlAccountEmail)
                .where(SqlAccountEmail.verified_email == "shared@example.test")
            )
            == 1
        )
