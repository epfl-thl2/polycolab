"""Offline prototype account recovery with delegated-access invalidation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.accounts.builtin import hash_password, normalize_username
from polycolab.db.models import (
    SqlAuthSession,
    SqlExternalAgentCredential,
    SqlExternalResearchRun,
    SqlLocalAccount,
    SqlOperatorAccountRecovery,
    SqlUser,
)
from polycolab.db.session import make_engine, make_session_factory
from polycolab.entities.time import utc_now
from polycolab.platform.config import get_settings


class OperatorRecoveryInvalid(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    account_id: UUID
    revoked_sessions: int
    revoked_credentials: int
    revoked_runs: int


def recover_account(
    session: Session,
    *,
    account_id: UUID,
    exact_username: str,
    new_password: str,
    verification_reference: str,
) -> RecoveryResult:
    """Replace a password only after two exact identifiers and offline verification."""

    if not 8 <= len(verification_reference.strip()) <= 500:
        raise OperatorRecoveryInvalid("verification reference must be 8-500 characters")
    try:
        username = normalize_username(exact_username)
        password_digest = hash_password(new_password)
    except ValueError as error:
        raise OperatorRecoveryInvalid(str(error)) from error
    now = utc_now()
    account = session.scalar(
        select(SqlLocalAccount).where(SqlLocalAccount.id == account_id).with_for_update()
    )
    if account is None or account.username != username:
        raise OperatorRecoveryInvalid("account identity does not match")
    user = session.scalar(
        select(SqlUser).where(
            SqlUser.issuer == "polycolab-local",
            SqlUser.subject == str(account.id),
        )
    )
    if user is None:
        raise OperatorRecoveryInvalid("built-in user identity is missing")
    auth_sessions = list(
        session.scalars(
            select(SqlAuthSession)
            .where(SqlAuthSession.account_id == account.id, SqlAuthSession.revoked_at.is_(None))
            .with_for_update()
        )
    )
    credentials = list(
        session.scalars(
            select(SqlExternalAgentCredential)
            .where(
                SqlExternalAgentCredential.sponsor_user_id == user.id,
                SqlExternalAgentCredential.revoked_at.is_(None),
            )
            .with_for_update()
        )
    )
    credential_ids = [credential.id for credential in credentials]
    runs = (
        list(
            session.scalars(
                select(SqlExternalResearchRun)
                .where(
                    SqlExternalResearchRun.credential_id.in_(credential_ids),
                    SqlExternalResearchRun.status == "OPEN",
                )
                .with_for_update()
            )
        )
        if credential_ids
        else []
    )
    for credential in credentials:
        credential.revoked_at = now
    for auth_session in auth_sessions:
        auth_session.revoked_at = now
    for run in runs:
        run.status = "REVOKED"
        run.closed_at = now
    account.password_digest = password_digest
    account.updated_at = now
    revoked_sessions = len(auth_sessions)
    session.add(
        SqlOperatorAccountRecovery(
            account_id=account.id,
            user_id=user.id,
            verification_reference_digest=hashlib.sha256(
                verification_reference.strip().encode("utf-8")
            ).hexdigest(),
            revoked_session_count=revoked_sessions,
            revoked_credential_count=len(credentials),
            revoked_run_count=len(runs),
        )
    )
    session.commit()
    return RecoveryResult(account.id, revoked_sessions, len(credentials), len(runs))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", type=UUID, required=True)
    parser.add_argument("--exact-username", required=True)
    parser.add_argument("--verification-reference", required=True)
    args = parser.parse_args(argv)
    password = os.environ.pop("POLYCOLAB_OPERATOR_RECOVERY_PASSWORD", None)
    if password is None:
        parser.error("POLYCOLAB_OPERATOR_RECOVERY_PASSWORD is required")
    engine = make_engine(get_settings())
    try:
        with make_session_factory(engine)() as session:
            result = recover_account(
                session,
                account_id=args.account_id,
                exact_username=args.exact_username,
                new_password=password,
                verification_reference=args.verification_reference,
            )
    except OperatorRecoveryInvalid as error:
        parser.error(str(error))
    finally:
        engine.dispose()
    print(
        json.dumps(
            {
                "account_id": str(result.account_id),
                "revoked_sessions": result.revoked_sessions,
                "revoked_credentials": result.revoked_credentials,
                "revoked_runs": result.revoked_runs,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
