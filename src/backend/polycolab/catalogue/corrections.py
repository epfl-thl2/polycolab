"""Optional human review of public-context corrections, not private publication."""

from uuid import UUID

from sqlalchemy.orm import Session

from polycolab.access.actors import Actor
from polycolab.access.authorization import require_human_actor
from polycolab.catalogue import admission as catalogue
from polycolab.catalogue.schemas import CatalogueRevise
from polycolab.db.models import SqlCorrectionDecision, SqlCorrectionSuggestion, SqlUser
from polycolab.platform.config import Settings
from polycolab.platform.outbox import append_event, canonical_digest
from polycolab.research import records
from polycolab.research.contracts import CorrectionDecisionRead, CorrectionDecisionWrite
from polycolab.research.objects import ResearchNotFound
from polycolab.workspaces.service import DomainConflict


def decision_read(value: SqlCorrectionDecision) -> CorrectionDecisionRead:
    """Project immutable decision rows into the current version vocabulary."""
    return CorrectionDecisionRead(
        suggestion_object_version_id=value.suggestion_revision_id,
        action=value.action,
        decided_object_version_id=value.decided_revision_id,
        reason=value.reason,
    )


def decide(
    session: Session,
    *,
    actor: Actor,
    settings: Settings,
    revision_id: UUID,
    payload: CorrectionDecisionWrite,
    key: str,
) -> CorrectionDecisionRead:
    require_human_actor(actor, action="public correction decision")
    try:
        scope = catalogue.lock_commons(session)
        # Private-context proposals cannot pass this public-release boundary.
        records.public_revision(session, revision_id)
        suggestion = session.get(SqlCorrectionSuggestion, revision_id)
        if suggestion is None:
            raise ResearchNotFound
        target = records.public_revision(session, suggestion.target_revision_id)
        user = session.get(SqlUser, actor.human_user_id)
        assert user is not None
        entry = catalogue.authorized_entry(session, entry_id=target.object_id, user=user)
        # Keep historical decision receipts stable across the live API rename.
        edited = (
            CatalogueRevise(
                **payload.edited.model_dump(exclude={"expected_current_object_version_id"}),
                base_revision_id=payload.edited.expected_current_object_version_id,
            )
            if payload.edited is not None
            else None
        )
        encoded = payload.model_dump(mode="json")
        encoded["edited"] = edited.model_dump(mode="json") if edited is not None else None
        digest = canonical_digest(encoded)
        existing = session.get(SqlCorrectionDecision, revision_id)
        if existing is not None:
            if existing.request_digest != digest:
                raise DomainConflict("suggestion already decided differently")
            result = decision_read(existing)
            session.commit()
            return result
        accepted_revision: UUID | None = None
        if payload.action != "REJECT":
            proposed = edited or CatalogueRevise.model_validate(suggestion.proposed)
            if proposed.base_revision_id != suggestion.target_revision_id:
                raise DomainConflict("review cannot silently rebase a correction")
            accepted_revision = catalogue.mutate(
                session,
                actor=actor,
                settings=settings,
                entry_id=entry.id,
                idempotency_key=canonical_digest(["correction", str(revision_id), key]),
                payload=proposed,
                commit=False,
            ).revision_id
        decision = SqlCorrectionDecision(
            suggestion_revision_id=revision_id,
            action=payload.action,
            decided_by_user_id=user.id,
            decided_revision_id=accepted_revision,
            request_digest=digest,
            reason=payload.reason,
        )
        session.add(decision)
        append_event(
            session,
            event_type="correction.decided",
            aggregate_type="catalogue_entry",
            aggregate_id=entry.id,
            ownership_scope_id=scope.id,
            payload={"suggestion_revision_id": str(revision_id), "action": payload.action},
        )
        session.flush()
        result = decision_read(decision)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
