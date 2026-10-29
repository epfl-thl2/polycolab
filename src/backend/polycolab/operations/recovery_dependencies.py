"""Read-only restore checks for canonical Garage bytes and credential decryption.

Run only against a quiescent isolated restore. No provider calls, database writes,
object uploads/deletes, or credential migration are performed.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from polycolab.artifacts.storage import ArtifactIntegrity, GarageStorage, garage_storage
from polycolab.db.models import (
    SqlArtifact,
    SqlGatewayProfile,
)
from polycolab.db.session import make_engine, make_session_factory
from polycolab.entities.enums import (
    ArtifactState,
)
from polycolab.model_gateway.credentials import (
    EncryptedCredential,
    KeyWrapper,
    credential_context,
    decrypt_credential,
    wrapper_from_settings,
)
from polycolab.platform.config import get_settings


@dataclass(frozen=True)
class DependencyReport:
    status: Literal["VERIFIED", "LIMIT_REACHED", "DATABASE_FAILURE", "DEPENDENCY_FAILURE"]
    checked: int


def _read_only(session: Session) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET TRANSACTION READ ONLY"))


def verify_artifacts(
    factory: sessionmaker[Session], storage: GarageStorage, *, max_items: int = 1000
) -> DependencyReport:
    """Verify committed bytes, not staging objects; end transactions before S3 I/O."""
    if type(max_items) is not int or not 1 <= max_items <= 1_000_000:
        raise ValueError("invalid item bound")
    checked = 0
    cursor: UUID | None = None
    while True:
        try:
            with factory() as session:
                _read_only(session)
                query = select(SqlArtifact).where(SqlArtifact.state == ArtifactState.COMMITTED)
                if cursor is not None:
                    query = query.where(SqlArtifact.id > cursor)
                rows = list(session.scalars(query.order_by(SqlArtifact.id).limit(100)))
            if not rows:
                return DependencyReport("VERIFIED", checked)
        except Exception:
            return DependencyReport("DATABASE_FAILURE", checked)
        for row in rows:
            if checked == max_items:
                return DependencyReport("LIMIT_REACHED", checked)
            try:
                storage.get_verified(
                    row.storage_key, ArtifactIntegrity(row.sha256, row.byte_length)
                )
            except Exception:
                return DependencyReport("DEPENDENCY_FAILURE", checked)
            checked += 1
            cursor = row.id


def verify_credentials(
    factory: sessionmaker[Session], wrapper: KeyWrapper, *, max_items: int = 1000
) -> DependencyReport:
    """Check all retained envelopes, including deleted profiles, without retaining plaintext."""
    if type(max_items) is not int or not 1 <= max_items <= 1_000_000:
        raise ValueError("invalid item bound")
    checked = 0
    cursor: UUID | None = None
    while True:
        try:
            with factory() as session:
                _read_only(session)
                query = select(SqlGatewayProfile)
                if cursor is not None:
                    query = query.where(SqlGatewayProfile.id > cursor)
                rows = list(session.scalars(query.order_by(SqlGatewayProfile.id).limit(100)))
            if not rows:
                return DependencyReport("VERIFIED", checked)
        except Exception:
            return DependencyReport("DATABASE_FAILURE", checked)
        for row in rows:
            if checked == max_items:
                return DependencyReport("LIMIT_REACHED", checked)
            try:
                decrypt_credential(
                    wrapper,
                    context=credential_context(user_id=row.user_id, profile_id=row.id),
                    encrypted=EncryptedCredential(
                        row.encrypted_credential, row.wrapped_data_key, row.encryption_key_version
                    ),
                )
            except Exception:
                return DependencyReport("DEPENDENCY_FAILURE", checked)
            checked += 1
            cursor = row.id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("artifacts", "credentials"))
    parser.add_argument("--isolated-restore", action="store_true", required=True)
    parser.add_argument("--max-items", type=int, default=1000)
    args = parser.parse_args(argv)
    if not 1 <= args.max_items <= 1_000_000:
        parser.error("--max-items must be 1-1000000")
    try:
        settings = get_settings()
        engine = make_engine(settings)
        try:
            factory = make_session_factory(engine)
            report: DependencyReport
            if args.kind == "artifacts":
                if (
                    settings.artifact_s3_endpoint is None
                    or settings.artifact_s3_bucket is None
                    or settings.artifact_s3_region is None
                    or settings.artifact_s3_access_key is None
                    or settings.artifact_s3_secret_key is None
                ):
                    raise ValueError("storage configuration required")
                storage = garage_storage(
                    endpoint=str(settings.artifact_s3_endpoint),
                    bucket=settings.artifact_s3_bucket,
                    region=settings.artifact_s3_region,
                    access_key=settings.artifact_s3_access_key.get_secret_value(),
                    secret_key=settings.artifact_s3_secret_key.get_secret_value(),
                )
                try:
                    report = verify_artifacts(factory, storage, max_items=args.max_items)
                finally:
                    storage.client.close()
            else:
                wrapper = wrapper_from_settings(settings)
                try:
                    report = verify_credentials(factory, wrapper, max_items=args.max_items)
                finally:
                    close = getattr(wrapper, "close", None)
                    if close is not None:
                        close()
        finally:
            engine.dispose()
    except Exception:
        print(json.dumps({"status": "CONFIGURATION_OR_RUNTIME_FAILURE"}))
        return 1
    print(json.dumps(asdict(report), sort_keys=True))
    return 0 if report.status == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
