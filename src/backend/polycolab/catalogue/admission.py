"""Human-only catalogue transactions. No network I/O or browser policy here."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor
from polycolab.access.authorization import AuthorizationDenied, require_catalogue_admission
from polycolab.catalogue.schemas import (
    CatalogueAdmit,
    CatalogueModerate,
    CatalogueModeratorUpdate,
    CatalogueMutationRead,
    CataloguePromote,
    CatalogueRevise,
    CatalogueSource,
    PublicStatementRead,
)
from polycolab.db.models import (
    SqlCatalogueAudit,
    SqlCatalogueEntry,
    SqlCatalogueModerator,
    SqlCatalogueModeratorAudit,
    SqlCatalogueRevision,
    SqlContributionEnvelope,
    SqlMutationReceipt,
    SqlObjectRevision,
    SqlPublicRelease,
    SqlResearchObject,
    SqlResearchScope,
    SqlStatementRevision,
    SqlUser,
)
from polycolab.entities.accounts import IdentifiedUser
from polycolab.entities.enums import (
    CanonicalEntityType,
    MutationReceiptStatus,
    ResearchEntityClass,
    ResearchObjectKind,
    ResearchScopeKind,
)
from polycolab.platform.config import Settings
from polycolab.platform.outbox import append_event, canonical_digest
from polycolab.research.contributions import human_contribution, link_output
from polycolab.research.objects import ResearchNotFound, add_revision_metadata, create_object
from polycolab.workspaces.service import DomainConflict


def _human(session: Session, actor: Actor) -> SqlUser:
    require_catalogue_admission(actor)
    user = session.get(SqlUser, actor.human_user_id)
    if user is None:
        raise AuthorizationDenied
    return user


def lock_commons(session: Session) -> SqlResearchScope:
    scope = session.scalar(
        select(SqlResearchScope)
        .where(SqlResearchScope.scope_kind == ResearchScopeKind.COMMONS)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if scope is None:
        raise ResearchNotFound
    return scope


def is_moderator(session: Session, user_id: UUID) -> bool:
    return (
        session.scalar(
            select(SqlCatalogueModerator.active).where(SqlCatalogueModerator.user_id == user_id)
        )
        is True
    )


def authorized_entry(
    session: Session, *, entry_id: UUID, user: IdentifiedUser, moderation: bool = False
) -> SqlCatalogueEntry:
    # Mutating callers hold the commons lock, shared with assignment/revocation.
    moderator = is_moderator(session, user.id)
    entry = session.get(SqlCatalogueEntry, entry_id, populate_existing=True)
    if entry is None or (entry.hidden and not moderator):
        raise ResearchNotFound
    if not moderator and (moderation or entry.admitted_by_user_id != user.id):
        raise AuthorizationDenied
    return entry


def _release(
    session: Session,
    obj: SqlResearchObject,
    revision: SqlObjectRevision,
    contribution: SqlContributionEnvelope,
) -> None:
    existing = session.scalar(
        select(SqlPublicRelease).where(SqlPublicRelease.object_revision_id == revision.id)
    )
    if existing is not None:
        return
    metadata = session.get(SqlStatementRevision, revision.id)
    author = session.get(SqlUser, revision.created_by_user_id)
    assert metadata is not None and author is not None
    fields = PublicStatementRead(
        object_id=obj.id,
        revision_id=revision.id,
        kind=cast(Literal["PROBLEM", "DEFINITION", "CLAIM"], obj.kind.value),
        title=revision.title,
        content_md=revision.content_md,
        assumptions_md=metadata.assumptions_md,
        author_display_name=author.display_name,
    ).model_dump(mode="json")
    session.add(
        SqlPublicRelease(
            ownership_scope_id=obj.ownership_scope_id,
            object_revision_id=revision.id,
            contribution_id=contribution.id,
            projection_version=1,
            public_fields=fields,
            public_fields_digest=canonical_digest(fields),
        )
    )


def _source(
    session: Session,
    entry: SqlCatalogueEntry,
    source: CatalogueSource | None,
    status: str,
    contribution: SqlContributionEnvelope,
    review_rationale: str | None = None,
    reviewer_id: UUID | None = None,
) -> None:
    session.add(
        SqlCatalogueRevision(
            revision_id=entry.official_revision_id,
            entry_id=entry.id,
            source_identifier=source.identifier if source else None,
            source_version=source.version if source else None,
            source_locator=source.locator if source else None,
            review_rationale=review_rationale,
            reviewed_by_user_id=reviewer_id if review_rationale else None,
            reviewed_at=datetime.now(UTC) if review_rationale else None,
            reported_status=status,
            contribution_id=contribution.id,
        )
    )


def mutate(
    session: Session,
    *,
    actor: Actor,
    settings: Settings,
    idempotency_key: str,
    payload: CatalogueAdmit | CataloguePromote | CatalogueRevise | CatalogueModerate,
    entry_id: UUID | None = None,
    commit: bool = True,
) -> CatalogueMutationRead:
    """Authorize under a scope lock and atomically commit exact durable results."""
    user = _human(session, actor)
    if not idempotency_key.strip() or len(idempotency_key) > 200:
        raise DomainConflict("invalid idempotency key")
    operation = {
        CatalogueAdmit: "ADMIT",
        CataloguePromote: "PROMOTE",
        CatalogueRevise: "REVISE",
        CatalogueModerate: "MODERATE",
    }[type(payload)]
    actor_key = f"human:{user.id}"
    operation_key = f"catalogue.{operation.lower()}"
    key_digest = canonical_digest(idempotency_key)
    receipt_payload = payload.model_dump(mode="json")
    # Preserve pre-Library receipts for requests without the new review field.
    if receipt_payload.get("review_rationale") is None:
        receipt_payload.pop("review_rationale", None)
    digest = canonical_digest(
        {"schema_version": 1, "entry_id": str(entry_id), "payload": receipt_payload}
    )
    try:
        if session.get_bind().dialect.name == "postgresql":
            lock_key = int(canonical_digest([actor_key, operation_key, key_digest])[:16], 16)
            if lock_key >= 2**63:
                lock_key -= 2**64
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        scope = lock_commons(session)
        entry = None
        if isinstance(payload, (CatalogueRevise, CatalogueModerate)):
            if entry_id is None:
                raise ResearchNotFound
            entry = authorized_entry(
                session,
                entry_id=entry_id,
                user=user,
                moderation=isinstance(payload, CatalogueModerate),
            )
        receipt = session.scalar(
            select(SqlMutationReceipt).where(
                SqlMutationReceipt.actor_key == actor_key,
                SqlMutationReceipt.operation == operation_key,
                SqlMutationReceipt.idempotency_key_digest == key_digest,
            )
        )
        if receipt is not None:
            if receipt.request_digest != digest:
                raise DomainConflict("idempotency payload mismatch")
            if entry is None:
                authorized_entry(session, entry_id=UUID(receipt.resource_ids[0]), user=user)
            result = CatalogueMutationRead(
                entry_id=UUID(receipt.resource_ids[0]), revision_id=UUID(receipt.resource_ids[1])
            )
            if commit:
                session.commit()
            return result
        if entry is not None and isinstance(payload, (CatalogueRevise, CatalogueModerate)):
            if entry.official_revision_id != payload.base_revision_id:
                raise DomainConflict("stale catalogue revision")
        envelope = human_contribution(
            session, user_id=user.id, scope_id=scope.id, operation=operation_key
        )
        obj: SqlResearchObject | None
        revision: SqlObjectRevision | None
        if isinstance(payload, CatalogueAdmit):
            obj, revision = create_object(
                session,
                ownership_scope_id=scope.id,
                kind=ResearchObjectKind(payload.kind),
                title=payload.title,
                content_md=payload.content_md,
                assumptions_md=payload.assumptions_md,
                rationale=payload.reason,
                author=user,
                actor=actor,
                contribution=envelope,
                commit=False,
            )
            entry = SqlCatalogueEntry(
                id=obj.id, official_revision_id=revision.id, admitted_by_user_id=user.id
            )
            session.add(entry)
            session.flush()
            _source(
                session,
                entry,
                payload.source,
                payload.reported_status,
                envelope,
                payload.review_rationale,
                user.id,
            )
            _release(session, obj, revision, envelope)
        elif isinstance(payload, CataloguePromote):
            revision = session.get(SqlObjectRevision, payload.revision_id)
            obj = session.get(SqlResearchObject, revision.object_id) if revision else None
            from polycolab.db.models import SqlRecordModeration

            moderation = session.get(SqlRecordModeration, obj.id) if obj else None
            if moderation is not None and moderation.hidden:
                raise ResearchNotFound
            release = session.scalar(
                select(SqlPublicRelease).where(
                    SqlPublicRelease.object_revision_id == payload.revision_id
                )
            )
            if (
                obj is None
                or revision is None
                or obj.ownership_scope_id != scope.id
                or obj.entity_class != ResearchEntityClass.STATEMENT
                or release is None
            ):
                raise ResearchNotFound
            if session.get(SqlCatalogueEntry, obj.id) is not None:
                raise DomainConflict("statement already admitted")
            if obj.current_revision_id != revision.id:
                raise DomainConflict("promote the current released revision")
            metadata = session.get(SqlStatementRevision, revision.id)
            if metadata is None or not metadata.assumptions_md.strip():
                raise DomainConflict("promotion requires explicit assumptions")
            # No copied object or invented authorship; admit the exact released revision.
            entry = SqlCatalogueEntry(
                id=obj.id, official_revision_id=revision.id, admitted_by_user_id=user.id
            )
            session.add(entry)
            session.flush()
            _source(session, entry, payload.source, payload.reported_status, envelope)
        elif isinstance(payload, CatalogueRevise):
            assert entry is not None
            obj = session.scalar(
                select(SqlResearchObject)
                .where(SqlResearchObject.id == entry.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            assert obj is not None
            base = session.get(SqlObjectRevision, obj.current_revision_id)
            assert base is not None
            if base.id != entry.official_revision_id:
                raise DomainConflict("statement has a newer revision; reconcile before editing")
            revision = SqlObjectRevision(
                object_id=obj.id,
                ownership_scope_id=scope.id,
                number=base.number + 1,
                base_revision_id=base.id,
                title=payload.title,
                content_md=payload.content_md,
                rationale=payload.reason,
                created_by_user_id=user.id,
                contribution_id=envelope.id,
            )
            session.add(revision)
            session.flush()
            add_revision_metadata(session, obj, revision, assumptions_md=payload.assumptions_md)
            obj.current_revision_id = revision.id
            entry.official_revision_id = revision.id
            link_output(
                session,
                envelope=envelope,
                entity_type=CanonicalEntityType.OBJECT_REVISION,
                entity_id=revision.id,
                scope_id=scope.id,
            )
            _source(
                session,
                entry,
                payload.source,
                payload.reported_status,
                envelope,
                payload.review_rationale,
                user.id,
            )
            _release(session, obj, revision, envelope)
        else:
            assert entry is not None
            entry.hidden = payload.action == "HIDE"
            operation = payload.action
        assert entry is not None
        session.add(
            SqlCatalogueAudit(
                entry_id=entry.id,
                revision_id=entry.official_revision_id,
                action=operation,
                reason=payload.reason,
                actor_user_id=user.id,
                contribution_id=envelope.id,
            )
        )
        result = CatalogueMutationRead(entry_id=entry.id, revision_id=entry.official_revision_id)
        session.add(
            SqlMutationReceipt(
                actor_key=actor_key,
                operation=operation_key,
                idempotency_key_digest=key_digest,
                request_digest=digest,
                status=MutationReceiptStatus.COMMITTED,
                resource_ids=[str(result.entry_id), str(result.revision_id)],
            )
        )
        append_event(
            session,
            event_type=f"catalogue.{operation.lower()}",
            aggregate_type="catalogue_entry",
            aggregate_id=entry.id,
            ownership_scope_id=scope.id,
            payload={"schema_version": 1, "revision_id": str(entry.official_revision_id)},
        )
        if commit:
            session.commit()
        else:
            session.flush()
        return result
    except Exception:
        session.rollback()
        raise


def assign_moderator(
    session: Session,
    *,
    actor: Actor,
    settings: Settings,
    user_id: UUID,
    payload: CatalogueModeratorUpdate,
) -> None:
    operator = _human(session, actor)
    if operator.subject not in settings.catalogue_operator_subjects:
        raise AuthorizationDenied
    try:
        scope = lock_commons(session)
        if session.get(SqlUser, user_id) is None:
            raise ResearchNotFound
        assignment = session.get(SqlCatalogueModerator, user_id, populate_existing=True)
        if assignment is None:
            session.add(SqlCatalogueModerator(user_id=user_id, active=payload.active))
        else:
            assignment.active = payload.active
        audit = SqlCatalogueModeratorAudit(
            user_id=user_id,
            operator_user_id=operator.id,
            active=payload.active,
            reason=payload.reason,
        )
        session.add(audit)
        session.flush()
        append_event(
            session,
            event_type="catalogue.moderator_changed",
            aggregate_type="catalogue_moderator_audit",
            aggregate_id=audit.id,
            ownership_scope_id=scope.id,
            payload={"schema_version": 1},
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
