"""Public discovery and separately authorized private workspace search."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select

from polycolab.app.access import Access
from polycolab.app.dependencies import DbSession
from polycolab.catalogue import discovery
from polycolab.db.models import SqlObjectRevision
from polycolab.entities.object_kinds import ObjectKind
from polycolab.research.read_access import collection_scope
from polycolab.research.routes.records import Cursor, Limit
from polycolab.research.version_projections import projected_version_reads
from polycolab.research.version_schemas import VersionDiscoveryHit, VersionDiscoveryPage

router = APIRouter(prefix="/api/v1", tags=["discovery"])
QueryText = Annotated[str, Query(max_length=500)]
FilterText = Annotated[str | None, Query(min_length=1, max_length=500)]


def public_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get(
    "/discovery",
    response_model=VersionDiscoveryPage,
    operation_id="searchPublicResearch",
    dependencies=[Depends(public_no_store)],
)
def public_search(
    session: DbSession,
    access: Access,
    workspace_id: UUID | None = None,
    scope: Literal["public", "member"] = "public",
    q: QueryText = "",
    kind: ObjectKind | None = None,
    statement_id: UUID | None = None,
    author: FilterText = None,
    status: FilterText = None,
    source: FilterText = None,
    limit: Limit = 25,
    cursor: Cursor = None,
) -> VersionDiscoveryPage:
    if scope == "member":
        workspace_id = collection_scope(session, access, scope, workspace_id)
    selected = discovery.search(
        session,
        project_id=workspace_id,
        public_only=scope == "public",
        query=q,
        kind=kind,
        statement_id=statement_id,
        author=author,
        status=status,
        source=source,
        limit=limit,
        cursor=cursor,
    )
    records = [hit.record for hit in selected.items]
    rows = {
        row.id: row
        for row in session.scalars(
            select(SqlObjectRevision).where(
                SqlObjectRevision.id.in_([record.revision_id for record in records])
            )
        )
    }
    versions = projected_version_reads(
        session,
        [rows[record.revision_id] for record in records],
        records,
        public=workspace_id is None,
    )
    return VersionDiscoveryPage(
        items=[
            VersionDiscoveryHit(object_version=version, **hit.model_dump(exclude={"record"}))
            for hit, version in zip(selected.items, versions, strict=True)
        ],
        next_cursor=selected.next_cursor,
    )
