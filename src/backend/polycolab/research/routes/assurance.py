"""Bounded authorized proof-assurance HTTP boundary."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from polycolab.app.access import Access
from polycolab.app.dependencies import CurrentActor, DbSession
from polycolab.catalogue.routes.catalogue import RetryKey, no_store
from polycolab.projects.service import DomainConflict
from polycolab.research import assurance
from polycolab.research.assurance_schemas import (
    ObjectVersionAssuranceRead,
    ObjectVersionCorrespondenceRead,
    ObjectVersionCorrespondenceWrite,
    ObjectVersionCurrentAssuranceRead,
    ObjectVersionEndorsementRead,
    ObjectVersionEndorsementWrite,
)
from polycolab.research.read_access import revision_scope

router = APIRouter(prefix="/api/v1", tags=["assurance"], dependencies=[Depends(no_store)])
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=200)]
LegacyAfter = Annotated[UUID | None, Query(deprecated=True)]


def _reject_legacy_cursor(after: UUID | None) -> None:
    if after is not None:
        raise DomainConflict("use the opaque chronological cursor")


@router.post(
    "/assurance/endorsements",
    response_model=ObjectVersionEndorsementRead,
    status_code=201,
    operation_id="endorseExactObjectVersion",
)
def endorse(
    payload: ObjectVersionEndorsementWrite, key: RetryKey, session: DbSession, actor: CurrentActor
) -> ObjectVersionEndorsementRead:
    return ObjectVersionEndorsementRead.model_validate(
        assurance.endorse(session, actor=actor, payload=payload.historical_command(), key=key)
    )


@router.post(
    "/assurance/correspondence",
    response_model=ObjectVersionCorrespondenceRead,
    status_code=201,
    operation_id="assessExactCorrespondence",
)
def assess(
    payload: ObjectVersionCorrespondenceWrite,
    key: RetryKey,
    session: DbSession,
    actor: CurrentActor,
) -> ObjectVersionCorrespondenceRead:
    return ObjectVersionCorrespondenceRead.model_validate(
        assurance.assess_correspondence(
            session, actor=actor, payload=payload.historical_command(), key=key
        )
    )


@router.get(
    "/assurance/{object_version_id}",
    response_model=ObjectVersionAssuranceRead,
    operation_id="getScopedObjectVersionAssurance",
)
def scoped_history(
    object_version_id: UUID,
    session: DbSession,
    access: Access,
    project_id: UUID | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
    after: LegacyAfter = None,
) -> ObjectVersionAssuranceRead:
    _reject_legacy_cursor(after)
    project_id = revision_scope(session, access, object_version_id, project_id)
    result = assurance.history(
        session,
        revision_id=object_version_id,
        project_id=project_id,
        limit=limit,
        cursor=cursor,
    )
    return ObjectVersionAssuranceRead.model_validate(result)


@router.get(
    "/assurance/{object_version_id}/current",
    response_model=ObjectVersionCurrentAssuranceRead,
    operation_id="getScopedObjectVersionCurrentAssurance",
)
def scoped_current(
    object_version_id: UUID,
    session: DbSession,
    access: Access,
    project_id: UUID | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
) -> ObjectVersionCurrentAssuranceRead:
    project_id = revision_scope(session, access, object_version_id, project_id)
    result = assurance.current(
        session,
        revision_id=object_version_id,
        project_id=project_id,
        limit=limit,
        cursor=cursor,
    )
    return ObjectVersionCurrentAssuranceRead.model_validate(result)
