"""Bounded operator-only credential migration; never invoked by API startup."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Literal

from sqlalchemy.orm import Session, sessionmaker

from polycolab.db.session import make_engine, make_session_factory
from polycolab.model_gateway.credentials import credential_context, wrapper_from_settings
from polycolab.model_gateway.migration import (
    CredentialKeyring,
    CredentialMigrationConflict,
    commit_rewrap_candidate,
    rewrap_snapshot_page,
)
from polycolab.platform.config import KmsProvider, get_settings


@dataclass(frozen=True)
class MigrationReport:
    selected: int
    migrated: int
    status: Literal["DRY_RUN", "PAGE_COMPLETE", "KEY_FAILURE", "CONFLICT", "DATABASE_FAILURE"]
    more_may_remain: bool


def migrate_page(
    factory: sessionmaker[Session],
    keyring: CredentialKeyring,
    *,
    apply: bool = False,
    limit: int = 100,
) -> MigrationReport:
    """Resume from canonical state: already-target envelopes are never selected.

    Stop at the first failure. Each successful profile update and its audit row
    commit together; rerunning is safe after interruption or ambiguous commits.
    Reports contain counts/status only, not profile IDs, fingerprints or secrets.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("migration limit must be between 1 and 100")
    try:
        with factory() as session:
            snapshots = rewrap_snapshot_page(
                session, target_version=keyring.key_version, limit=limit
            )
        # The read session is closed before any key-service operation begins.
    except Exception:
        return MigrationReport(0, 0, "DATABASE_FAILURE", True)
    selected = len(snapshots)
    if not apply:
        return MigrationReport(selected, 0, "DRY_RUN", selected == limit)
    migrated = 0
    for snapshot in snapshots:
        try:
            candidate = keyring.prepare_rewrap(
                context=credential_context(
                    user_id=snapshot.user_id, profile_id=snapshot.profile_id
                ),
                encrypted=snapshot.encrypted,
                target_version=keyring.key_version,
            )
        except Exception:
            return MigrationReport(selected, migrated, "KEY_FAILURE", True)
        try:
            with factory() as session:
                commit_rewrap_candidate(session, snapshot=snapshot, candidate=candidate)
        except CredentialMigrationConflict:
            return MigrationReport(selected, migrated, "CONFLICT", True)
        except Exception:
            # A failed post-commit refresh can be ambiguous. Do not undo or
            # blindly replay the write; the next invocation re-reads state.
            return MigrationReport(selected, migrated, "DATABASE_FAILURE", True)
        migrated += 1
    return MigrationReport(selected, migrated, "PAGE_COMPLETE", selected == limit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="commit verified rewraps (default: count only)"
    )
    parser.add_argument("--limit", type=int, default=100, help="maximum profiles, 1-100")
    parser.add_argument(
        "--expected-target-version", help="required exact envelope version for --apply"
    )
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    if args.apply and not args.expected_target_version:
        parser.error("--apply requires --expected-target-version")
    # Never print Settings, SQL exceptions or upstream exceptions: they can
    # contain operator credentials, connection strings or encrypted envelopes.
    try:
        settings = get_settings()
        if settings.kms_provider is not KmsProvider.OPENBAO:
            raise ValueError
        selected = wrapper_from_settings(settings)
        if not isinstance(selected, CredentialKeyring):
            raise ValueError
        try:
            if args.apply and args.expected_target_version != selected.key_version:
                raise ValueError
            engine = make_engine(settings)
            try:
                report = migrate_page(
                    make_session_factory(engine), selected, apply=args.apply, limit=args.limit
                )
            finally:
                engine.dispose()
        finally:
            selected.close()
    except Exception:
        print(json.dumps({"status": "CONFIGURATION_OR_RUNTIME_FAILURE"}))
        return 1
    print(json.dumps(asdict(report), sort_keys=True))
    return 0 if report.status in {"DRY_RUN", "PAGE_COMPLETE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
