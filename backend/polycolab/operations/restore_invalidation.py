"""Invalidate every restored browser and external-agent protected-access grant."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from polycolab.db.models import (
    SqlAuthSession,
    SqlExternalAgentCredential,
    SqlExternalResearchRun,
    SqlOperatorRestoreInvalidation,
)
from polycolab.db.session import make_engine, make_session_factory
from polycolab.entities.time import utc_now
from polycolab.platform.config import get_settings


class RestoreInvalidationInvalid(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RestoreInvalidationResult:
    revoked_sessions: int
    revoked_credentials: int
    revoked_runs: int


def invalidate_restored_protected_access(
    session: Session,
    *,
    recovery_reference: str,
) -> RestoreInvalidationResult:
    """Revoke the complete restored cohort in one database transaction."""

    reference = recovery_reference.strip()
    if not 8 <= len(reference) <= 500:
        raise RestoreInvalidationInvalid("recovery reference must be 8-500 characters")
    observed_at = utc_now()
    revoked_sessions = cast(
        CursorResult[Any],
        session.execute(
            update(SqlAuthSession)
            .where(SqlAuthSession.revoked_at.is_(None))
            .values(revoked_at=observed_at)
        ),
    ).rowcount
    revoked_credentials = cast(
        CursorResult[Any],
        session.execute(
            update(SqlExternalAgentCredential)
            .where(SqlExternalAgentCredential.revoked_at.is_(None))
            .values(revoked_at=observed_at)
        ),
    ).rowcount
    revoked_runs = cast(
        CursorResult[Any],
        session.execute(
            update(SqlExternalResearchRun)
            .where(SqlExternalResearchRun.status == "OPEN")
            .values(status="REVOKED", closed_at=observed_at)
        ),
    ).rowcount
    result = RestoreInvalidationResult(
        revoked_sessions=max(revoked_sessions or 0, 0),
        revoked_credentials=max(revoked_credentials or 0, 0),
        revoked_runs=max(revoked_runs or 0, 0),
    )
    session.add(
        SqlOperatorRestoreInvalidation(
            recovery_reference_digest=hashlib.sha256(reference.encode("utf-8")).hexdigest(),
            revoked_session_count=result.revoked_sessions,
            revoked_credential_count=result.revoked_credentials,
            revoked_run_count=result.revoked_runs,
        )
    )
    session.commit()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-restored-cohort-invalidation",
        action="store_true",
        help="confirm that restored ingress is quiesced and every old grant must be revoked",
    )
    parser.add_argument("--recovery-reference", required=True)
    args = parser.parse_args(argv)
    if not args.confirm_restored_cohort_invalidation:
        parser.error("--confirm-restored-cohort-invalidation is required")
    engine = make_engine(get_settings())
    try:
        with make_session_factory(engine)() as session:
            try:
                result = invalidate_restored_protected_access(
                    session,
                    recovery_reference=args.recovery_reference,
                )
            except RestoreInvalidationInvalid as error:
                parser.error(str(error))
    finally:
        engine.dispose()
    print(
        json.dumps(
            {
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
