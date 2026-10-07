"""Small durable retry primitives; callers own authorization and transactions."""

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from polycolab.db.models import SqlMutationReceipt
from polycolab.entities.enums import MutationReceiptStatus
from polycolab.platform.outbox import canonical_digest
from polycolab.workspaces.service import DomainConflict


def lock_key(session: Session, actor_key: str, operation: str, key: str) -> None:
    if not key.strip() or len(key) > 200:
        raise DomainConflict("invalid retry key")
    if session.get_bind().dialect.name == "postgresql":
        number = int(canonical_digest([actor_key, operation, key])[:16], 16)
        if number >= 2**63:
            number -= 2**64
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": number})


def receipt(
    session: Session, actor_key: str, operation: str, key: str, payload: object
) -> SqlMutationReceipt | None:
    value = session.scalar(
        select(SqlMutationReceipt).where(
            SqlMutationReceipt.actor_key == actor_key,
            SqlMutationReceipt.operation == operation,
            SqlMutationReceipt.idempotency_key_digest == canonical_digest(key),
        )
    )
    if value is not None and value.request_digest != canonical_digest(
        {"version": 1, "payload": payload}
    ):
        raise DomainConflict("retry payload mismatch")
    return value


def save(
    session: Session, actor_key: str, operation: str, key: str, payload: object, ids: list[UUID]
) -> None:
    session.add(
        SqlMutationReceipt(
            actor_key=actor_key,
            operation=operation,
            idempotency_key_digest=canonical_digest(key),
            request_digest=canonical_digest({"version": 1, "payload": payload}),
            status=MutationReceiptStatus.COMMITTED,
            resource_ids=[str(value) for value in ids],
        )
    )
