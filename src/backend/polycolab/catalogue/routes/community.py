"""Human community intent and anonymous aggregate interest, never follower identities."""

from uuid import UUID

from fastapi import APIRouter, Depends

from polycolab.app.access import research_access
from polycolab.app.dependencies import CurrentActor, CurrentUser, DbSession
from polycolab.catalogue import community
from polycolab.catalogue.routes.catalogue import no_store
from polycolab.research.contracts import (
    CommunityState,
    CommunityToggle,
    ProgressSummaryRead,
    PublicCommunityState,
    ResearchNotificationPage,
)
from polycolab.research.routes.records import Cursor, Limit

router = APIRouter(prefix="/api/v1", tags=["community"], dependencies=[Depends(no_store)])


@router.get(
    "/notifications",
    response_model=ResearchNotificationPage,
    operation_id="listMyResearchNotifications",
)
def notifications(
    session: DbSession, user: CurrentUser, limit: Limit = 25, cursor: Cursor = None
) -> ResearchNotificationPage:
    from polycolab.research.notifications import read_notifications

    return ResearchNotificationPage.model_validate(
        read_notifications(session, user_id=user.id, limit=limit, cursor=cursor)
    )


@router.get(
    "/community/{entry_id}/summary",
    dependencies=[Depends(research_access)],
    response_model=ProgressSummaryRead,
    operation_id="getPublicProgressSummary",
)
def summary(entry_id: UUID, session: DbSession) -> ProgressSummaryRead:
    from polycolab.research.notifications import read_summary

    return ProgressSummaryRead.model_validate(read_summary(session, entry_id))


@router.put(
    "/community/{entry_id}/follow", response_model=CommunityState, operation_id="setCatalogueFollow"
)
def follow(
    entry_id: UUID, payload: CommunityToggle, session: DbSession, actor: CurrentActor
) -> CommunityState:
    return community.toggle(
        session, actor=actor, entry_id=entry_id, follow=True, active=payload.active
    )


@router.put(
    "/community/{entry_id}/interest",
    response_model=CommunityState,
    operation_id="setCatalogueInterest",
)
def interest(
    entry_id: UUID, payload: CommunityToggle, session: DbSession, actor: CurrentActor
) -> CommunityState:
    return community.toggle(
        session, actor=actor, entry_id=entry_id, follow=False, active=payload.active
    )


@router.get(
    "/community/{entry_id}/me",
    response_model=CommunityState,
    operation_id="getMyCatalogueCommunityState",
)
def personal(entry_id: UUID, session: DbSession, user: CurrentUser) -> CommunityState:
    return community.state(session, entry_id, user.id)


@router.get(
    "/community/{entry_id}",
    dependencies=[Depends(research_access)],
    response_model=PublicCommunityState,
    operation_id="getPublicCatalogueInterest",
)
def public(entry_id: UUID, session: DbSession) -> PublicCommunityState:
    return PublicCommunityState(interest_count=community.interest_count(session, entry_id))
