"""Catalogue HTTP boundary; trusted actors and policy live in domain services."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import select

from polycolab.app.access import research_access
from polycolab.app.dependencies import CurrentActor, DbSession
from polycolab.catalogue import admission as catalogue
from polycolab.catalogue import projections as public_projections
from polycolab.catalogue.read_schemas import (
    CatalogueVersionMutationRead,
    PublicCataloguePage,
    PublicCatalogueRead,
)
from polycolab.catalogue.schemas import (
    CatalogueAuditRead,
    CatalogueModerate,
    CatalogueModerationWrite,
    CatalogueModeratorUpdate,
    CatalogueObjectAdmit,
    CataloguePromote,
    CataloguePromotionWrite,
    CatalogueRevise,
    CatalogueVersionCreate,
)
from polycolab.db.models import SqlCatalogueAudit, SqlUser


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/api/v1", tags=["catalogue"])

RetryKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


@router.get(
    "/library",
    response_model=PublicCataloguePage,
    dependencies=[Depends(research_access), Depends(no_store)],
    operation_id="searchLibrary",
)
def search_library(
    session: DbSession,
    q: Annotated[str, Query(max_length=500)] = "",
    kind: Literal["PROBLEM", "STATEMENT", "DEFINITION"] | None = None,
    status: Annotated[str | None, Query(max_length=200)] = None,
    basis: Literal["literature", "review"] | None = None,
    source: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> PublicCataloguePage:
    try:
        return public_projections.library_page(
            session,
            query=q,
            kind="CLAIM" if kind == "STATEMENT" else kind,
            status=status,
            basis=basis,
            source=source,
            limit=limit,
            cursor=cursor,
        )
    except ValueError:
        raise HTTPException(422, "Invalid Library cursor") from None


@router.get(
    "/catalogue/{entry_id}/history",
    response_model=PublicCataloguePage,
    operation_id="listCatalogueHistory",
    dependencies=[Depends(research_access), Depends(no_store)],
)
def public_history(
    entry_id: UUID,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> PublicCataloguePage:
    public_projections.require_catalogue_entry(session, entry_id)
    try:
        return public_projections.library_page(
            session, entry_id=entry_id, limit=limit, cursor=cursor
        )
    except ValueError:
        raise HTTPException(422, "Invalid Library cursor") from None


@router.get(
    "/catalogue/{entry_id}/versions/{object_version_id}",
    response_model=PublicCatalogueRead,
    operation_id="getCatalogueVersion",
    dependencies=[Depends(research_access), Depends(no_store)],
)
def public_version(
    entry_id: UUID, object_version_id: UUID, session: DbSession
) -> PublicCatalogueRead:
    return public_projections.catalogue_entry(session, entry_id, object_version_id)


@router.post(
    "/catalogue",
    response_model=CatalogueVersionMutationRead,
    status_code=201,
    dependencies=[Depends(no_store)],
    operation_id="admitCatalogueEntry",
)
def admit(
    payload: CatalogueObjectAdmit,
    key: RetryKey,
    request: Request,
    session: DbSession,
    actor: CurrentActor,
) -> CatalogueVersionMutationRead:
    result = catalogue.mutate(
        session,
        actor=actor,
        settings=request.app.state.settings,
        idempotency_key=key,
        payload=payload.historical_command(),
    )
    return CatalogueVersionMutationRead(
        entry_id=result.entry_id, object_version_id=result.revision_id
    )


@router.post(
    "/catalogue/promotions",
    response_model=CatalogueVersionMutationRead,
    status_code=201,
    dependencies=[Depends(no_store)],
    operation_id="promoteCatalogueStatement",
)
def promote(
    payload: CataloguePromotionWrite,
    key: RetryKey,
    request: Request,
    session: DbSession,
    actor: CurrentActor,
) -> CatalogueVersionMutationRead:
    result = catalogue.mutate(
        session,
        actor=actor,
        settings=request.app.state.settings,
        idempotency_key=key,
        payload=CataloguePromote(
            **payload.model_dump(exclude={"object_version_id"}),
            revision_id=payload.object_version_id,
        ),
    )
    return CatalogueVersionMutationRead(
        entry_id=result.entry_id, object_version_id=result.revision_id
    )


@router.post(
    "/catalogue/{entry_id}/versions",
    response_model=CatalogueVersionMutationRead,
    status_code=201,
    dependencies=[Depends(no_store)],
    operation_id="createCatalogueVersion",
)
def revise(
    entry_id: UUID,
    payload: CatalogueVersionCreate,
    key: RetryKey,
    request: Request,
    session: DbSession,
    actor: CurrentActor,
) -> CatalogueVersionMutationRead:
    result = catalogue.mutate(
        session,
        actor=actor,
        settings=request.app.state.settings,
        idempotency_key=key,
        payload=CatalogueRevise(
            **payload.model_dump(exclude={"expected_current_object_version_id"}),
            base_revision_id=payload.expected_current_object_version_id,
        ),
        entry_id=entry_id,
    )
    return CatalogueVersionMutationRead(
        entry_id=result.entry_id, object_version_id=result.revision_id
    )


@router.post(
    "/catalogue/{entry_id}/moderation",
    response_model=CatalogueVersionMutationRead,
    dependencies=[Depends(no_store)],
    operation_id="moderateCatalogueEntry",
)
def moderate(
    entry_id: UUID,
    payload: CatalogueModerationWrite,
    key: RetryKey,
    request: Request,
    session: DbSession,
    actor: CurrentActor,
) -> CatalogueVersionMutationRead:
    result = catalogue.mutate(
        session,
        actor=actor,
        settings=request.app.state.settings,
        idempotency_key=key,
        payload=CatalogueModerate(
            **payload.model_dump(exclude={"expected_current_object_version_id"}),
            base_revision_id=payload.expected_current_object_version_id,
        ),
        entry_id=entry_id,
    )
    return CatalogueVersionMutationRead(
        entry_id=result.entry_id, object_version_id=result.revision_id
    )


@router.put(
    "/catalogue-moderators/{user_id}",
    status_code=204,
    dependencies=[Depends(no_store)],
    operation_id="assignCatalogueModerator",
)
def assign(
    user_id: UUID,
    payload: CatalogueModeratorUpdate,
    request: Request,
    session: DbSession,
    actor: CurrentActor,
) -> None:
    catalogue.assign_moderator(
        session, actor=actor, settings=request.app.state.settings, user_id=user_id, payload=payload
    )


@router.get(
    "/catalogue/{entry_id}/audit",
    response_model=list[CatalogueAuditRead],
    dependencies=[Depends(no_store)],
    operation_id="listCatalogueAudit",
)
def audit(
    entry_id: UUID,
    session: DbSession,
    actor: CurrentActor,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    after: UUID | None = None,
) -> list[CatalogueAuditRead]:
    user = session.get(SqlUser, actor.human_user_id)
    if user is None:
        raise HTTPException(403)
    catalogue.authorized_entry(session, entry_id=entry_id, user=user)
    query = select(SqlCatalogueAudit).where(SqlCatalogueAudit.entry_id == entry_id)
    if after is not None:
        query = query.where(SqlCatalogueAudit.id > after)
    return [
        CatalogueAuditRead(
            id=row.id,
            object_version_id=row.revision_id,
            action=row.action,
            reason=row.reason,
            actor_user_id=row.actor_user_id,
            created_at=row.created_at,
        )
        for row in session.scalars(query.order_by(SqlCatalogueAudit.id).limit(limit))
    ]


@router.get(
    "/catalogue",
    response_model=PublicCataloguePage,
    dependencies=[Depends(research_access), Depends(no_store)],
    operation_id="listPublicCatalogue",
)
def list_public(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> PublicCataloguePage:
    try:
        return public_projections.catalogue_page(session, limit=limit, cursor=cursor)
    except ValueError:
        raise HTTPException(422) from None


@router.get(
    "/catalogue/{entry_id}",
    response_model=PublicCatalogueRead,
    dependencies=[Depends(research_access), Depends(no_store)],
    operation_id="getPublicCatalogueEntry",
)
def get_public(entry_id: UUID, session: DbSession) -> PublicCatalogueRead:
    return public_projections.catalogue_entry(session, entry_id)
