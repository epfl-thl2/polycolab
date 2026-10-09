"""Independent idempotent community intent, without endorsement semantics."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor
from polycolab.access.authorization import require_human_actor
from polycolab.catalogue.admission import lock_commons
from polycolab.catalogue.projections import require_catalogue_entry
from polycolab.db.models import SqlCatalogueFollow, SqlCatalogueInterest
from polycolab.research.contracts import CommunityState


def interest_count(session: Session, entry_id: UUID) -> int:
    require_catalogue_entry(session, entry_id)
    return (
        session.scalar(
            select(func.count())
            .select_from(SqlCatalogueInterest)
            .where(
                SqlCatalogueInterest.entry_id == entry_id,
                SqlCatalogueInterest.active.is_(True),
            )
        )
        or 0
    )


def state(session: Session, entry_id: UUID, user_id: UUID) -> CommunityState:
    count = interest_count(session, entry_id)
    follow = session.get(SqlCatalogueFollow, (user_id, entry_id))
    vote = session.get(SqlCatalogueInterest, (user_id, entry_id))
    return CommunityState(
        following=bool(follow and follow.active),
        interested=bool(vote and vote.active),
        interest_count=count,
    )


def toggle(
    session: Session, *, actor: Actor, entry_id: UUID, follow: bool, active: bool
) -> CommunityState:
    require_human_actor(actor, action="community participation")
    assert actor.human_user_id is not None
    try:
        lock_commons(session)
        require_catalogue_entry(session, entry_id)
        model = SqlCatalogueFollow if follow else SqlCatalogueInterest
        value = (
            session.get(SqlCatalogueFollow, (actor.human_user_id, entry_id), populate_existing=True)
            if follow
            else session.get(
                SqlCatalogueInterest, (actor.human_user_id, entry_id), populate_existing=True
            )
        )
        if value is None:
            session.add(model(user_id=actor.human_user_id, entry_id=entry_id, active=active))
        else:
            value.active = active
        session.flush()
        result = state(session, entry_id, actor.human_user_id)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
