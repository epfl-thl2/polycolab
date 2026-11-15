"""Small durable retry primitives; callers own authorization and transactions."""

import hashlib
import json
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from polycolab.db.models import SqlIdempotencyRecord
from polycolab.entities.enums import IdempotencyRecordStatus
from polycolab.platform.project_history import idempotency_operation, idempotency_payload
from polycolab.projects.service import DomainConflict


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def lock_key(session: Session, actor_key: str, operation: str, key: str) -> None:
    operation = idempotency_operation(operation)
    if not key.strip() or len(key) > 200:
        raise DomainConflict("invalid retry key")
    if session.get_bind().dialect.name == "postgresql":
        number = int(canonical_digest([actor_key, operation, key])[:16], 16)
        if number >= 2**63:
            number -= 2**64
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": number})


def record(
    session: Session,
    actor_key: str,
    operation: str,
    key: str,
    payload: object,
    *,
    authorize: Callable[[SqlIdempotencyRecord], None] | None = None,
) -> SqlIdempotencyRecord | None:
    payload = idempotency_payload(operation, payload)
    operation = idempotency_operation(operation)
    value = session.scalar(
        select(SqlIdempotencyRecord).where(
            SqlIdempotencyRecord.actor_key == actor_key,
            SqlIdempotencyRecord.operation == operation,
            SqlIdempotencyRecord.idempotency_key_digest == canonical_digest(key),
        )
    )
    if value is not None and authorize is not None:
        authorize(value)
    if value is not None and value.request_digest != canonical_digest(
        {"version": 1, "payload": payload}
    ):
        raise DomainConflict("retry payload mismatch")
    return value


def save(
    session: Session, actor_key: str, operation: str, key: str, payload: object, ids: list[UUID]
) -> None:
    payload = idempotency_payload(operation, payload)
    operation = idempotency_operation(operation)
    session.add(
        SqlIdempotencyRecord(
            actor_key=actor_key,
            operation=operation,
            idempotency_key_digest=canonical_digest(key),
            request_digest=canonical_digest({"version": 1, "payload": payload}),
            status=IdempotencyRecordStatus.COMMITTED,
            resource_ids=[str(value) for value in ids],
        )
    )
