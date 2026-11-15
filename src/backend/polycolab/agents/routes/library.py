"""Public releases and human-only contribution endpoints."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from functools import partial
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import Field, field_validator

from polycolab.agents.library import service
from polycolab.app.cursors import Collection, Pagination
from polycolab.app.dependencies import CurrentUser, RequestTransaction
from polycolab.app.schemas import ApiModel, RequestModel
from polycolab.entities.library import (
    LibraryContent,
    LibraryItem,
    LibraryKind,
    LibraryOwned,
    LibraryPublic,
    LibraryVersion,
)
from polycolab.projects.service import DomainConflict
from polycolab.transaction import PersistenceConflict

router = APIRouter(prefix="/api/v1/library", tags=["library"])
RetryKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


class LibraryContentWrite(RequestModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=2000)
    content: str = Field(default="", max_length=200_000)
    instructions: str = Field(default="", max_length=20_000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    license: str = Field(default="", max_length=300)
    source_url: str = Field(default="", max_length=2000)
    runtime: str = Field(default="", max_length=100)
    source_reference: str = Field(default="", max_length=300)

    @field_validator("title", "description")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain text")
        return value

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, values: list[str]) -> list[str]:
        values = list(dict.fromkeys(value.strip().lower() for value in values))
        if any(not value or len(value) > 64 for value in values):
            raise ValueError("tags must contain 1 to 64 characters")
        return values

    @field_validator("source_url")
    @classmethod
    def web_url(cls, value: str) -> str:
        if value:
            url = urlsplit(value)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or any(ord(c) <= 32 for c in value)
            ):
                raise ValueError("source must be an HTTP or HTTPS URL without credentials")
        return value

    def entity(self) -> LibraryContent:
        return LibraryContent(**{**self.model_dump(exclude={"tags"}), "tags": tuple(self.tags)})


class LibraryContentRead(LibraryContentWrite, ApiModel):
    pass


class LibraryCreate(RequestModel):
    kind: LibraryKind
    content: LibraryContentWrite


class LibraryRevisionWrite(RequestModel):
    expected_revision: int = Field(ge=1)


class LibraryDraftWrite(LibraryRevisionWrite):
    content: LibraryContentWrite


class LibraryArchiveWrite(LibraryRevisionWrite):
    archived: bool


class LibraryModerateWrite(LibraryRevisionWrite):
    hidden: bool
    reason: str = Field(min_length=1, max_length=4000)

    @field_validator("reason")
    @classmethod
    def reason_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must contain text")
        return value


class LibraryCopyWrite(RequestModel):
    version_id: UUID


class LibraryItemRead(ApiModel):
    id: UUID
    owner_user_id: UUID
    kind: LibraryKind
    revision: int
    published_version_id: UUID | None
    source_version_id: UUID | None
    archived: bool
    hidden: bool
    created_at: datetime


class LibraryVersionRead(ApiModel):
    id: UUID
    item_id: UUID
    number: int
    content: LibraryContentRead
    author_user_id: UUID
    author_name: str
    published_at: datetime


class LibraryOwnedRead(ApiModel):
    item: LibraryItemRead
    draft: LibraryContentRead
    source_item_id: UUID | None


class LibraryPublicRead(ApiModel):
    id: UUID
    kind: LibraryKind
    source_version_id: UUID | None
    archived: bool
    version: LibraryVersionRead
    source_item_id: UUID | None


def call[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except service.LibraryError as error:
        raise HTTPException(error.status, error.code) from None
    except DomainConflict, PersistenceConflict:
        raise HTTPException(409, "library_conflict") from None


def private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


@router.get("", response_model=Collection[LibraryPublicRead], operation_id="listLibrary")
def listing(
    tx: RequestTransaction,
    page: Pagination,
    kind: LibraryKind | None = None,
    q: str = Query(default="", max_length=200),
    tag: str = Query(default="", max_length=64),
) -> Collection[LibraryPublicRead]:
    scope = f"library:public:{kind}:{q}:{tag}"
    rows = tx.library.public_items(
        kind=kind,
        q=q,
        tag=tag.strip().lower(),
        after=page.after_uuid(scope=scope),
        limit=page.limit + 1,
    )
    items = [
        LibraryPublicRead.model_validate(asdict(call(partial(service.public, tx, row.id))))
        for row in rows[: page.limit]
    ]
    return Collection(
        items=items,
        next_cursor=page.next_uuid(rows[page.limit - 1].id, scope=scope)
        if len(rows) > page.limit
        else None,
    )


@router.get("/mine", response_model=Collection[LibraryOwnedRead], operation_id="listOwnedLibrary")
def mine(
    tx: RequestTransaction,
    user: CurrentUser,
    page: Pagination,
    response: Response,
    kind: LibraryKind | None = None,
    q: str = Query(default="", max_length=200),
    tag: str = Query(default="", max_length=64),
) -> Collection[LibraryOwnedRead]:
    private(response)
    scope = f"library:owner:{user.id}:{kind}:{q}:{tag}"
    rows = tx.library.owned_items(
        user.id,
        kind=kind,
        q=q,
        tag=tag.strip().lower(),
        after=page.after_uuid(scope=scope),
        limit=page.limit + 1,
    )
    return Collection(
        items=[LibraryOwnedRead.model_validate(asdict(row)) for row in rows[: page.limit]],
        next_cursor=page.next_uuid(rows[page.limit - 1].item.id, scope=scope)
        if len(rows) > page.limit
        else None,
    )


@router.post("", response_model=LibraryOwnedRead, status_code=201, operation_id="createLibraryItem")
def create(
    payload: LibraryCreate,
    tx: RequestTransaction,
    user: CurrentUser,
    key: RetryKey,
    response: Response,
) -> LibraryOwned:
    private(response)
    return call(lambda: service.create(tx, user, payload.kind, payload.content.entity(), key))


@router.get("/{item_id}/draft", response_model=LibraryOwnedRead, operation_id="getLibraryDraft")
def draft(
    item_id: UUID, tx: RequestTransaction, user: CurrentUser, response: Response
) -> LibraryOwned:
    private(response)
    return call(lambda: service.owned(tx, item_id, user))


@router.put("/{item_id}/draft", response_model=LibraryOwnedRead, operation_id="updateLibraryDraft")
def update(
    item_id: UUID,
    payload: LibraryDraftWrite,
    tx: RequestTransaction,
    user: CurrentUser,
    key: RetryKey,
    response: Response,
) -> LibraryOwned:
    private(response)
    return call(
        lambda: service.update(
            tx, user, item_id, payload.content.entity(), payload.expected_revision, key
        )
    )


@router.post(
    "/{item_id}/publish",
    response_model=LibraryVersionRead,
    operation_id="publishLibraryItem",
)
def publish(
    item_id: UUID,
    payload: LibraryRevisionWrite,
    tx: RequestTransaction,
    user: CurrentUser,
    key: RetryKey,
    response: Response,
) -> LibraryVersion:
    private(response)
    return call(lambda: service.publish(tx, user, item_id, payload.expected_revision, key))


@router.post(
    "/{item_id}/copy",
    response_model=LibraryOwnedRead,
    status_code=201,
    operation_id="copyLibraryItem",
)
def copy(
    item_id: UUID,
    payload: LibraryCopyWrite,
    tx: RequestTransaction,
    user: CurrentUser,
    key: RetryKey,
    response: Response,
) -> LibraryOwned:
    private(response)
    return call(lambda: service.copy(tx, user, item_id, payload.version_id, key))


@router.post(
    "/{item_id}/archive", response_model=LibraryOwnedRead, operation_id="archiveLibraryItem"
)
def archive(
    item_id: UUID,
    payload: LibraryArchiveWrite,
    tx: RequestTransaction,
    user: CurrentUser,
    key: RetryKey,
    response: Response,
) -> LibraryOwned:
    private(response)
    return call(
        lambda: service.archive(tx, user, item_id, payload.expected_revision, payload.archived, key)
    )


@router.get(
    "/{item_id}/moderation",
    response_model=LibraryItemRead,
    operation_id="getLibraryModerationState",
)
def moderation_state(
    item_id: UUID, tx: RequestTransaction, user: CurrentUser, request: Request, response: Response
) -> LibraryItem:
    private(response)
    if user.subject not in request.app.state.settings.library_moderator_subjects:
        raise HTTPException(403, "library_moderation_denied")
    return call(lambda: service.required(tx, item_id))


@router.post(
    "/{item_id}/moderation",
    response_model=LibraryItemRead,
    operation_id="moderateLibraryItem",
)
def moderate(
    item_id: UUID,
    payload: LibraryModerateWrite,
    tx: RequestTransaction,
    user: CurrentUser,
    key: RetryKey,
    request: Request,
    response: Response,
) -> LibraryItem:
    private(response)
    return call(
        lambda: service.moderate(
            tx,
            user,
            item_id,
            payload.expected_revision,
            payload.hidden,
            payload.reason,
            key,
            request.app.state.settings.library_moderator_subjects,
        )
    )


@router.get("/{item_id}", response_model=LibraryPublicRead, operation_id="getLibraryItem")
def detail(item_id: UUID, tx: RequestTransaction) -> LibraryPublic:
    return call(lambda: service.public(tx, item_id))


@router.get(
    "/{item_id}/versions",
    response_model=Collection[LibraryVersionRead],
    operation_id="listLibraryVersions",
)
def versions(
    item_id: UUID, tx: RequestTransaction, page: Pagination
) -> Collection[LibraryVersionRead]:
    call(lambda: service.public(tx, item_id))
    scope = f"library:versions:{item_id}"
    rows = tx.library.versions(item_id, after=page.after_uuid(scope=scope), limit=page.limit + 1)
    return Collection(
        items=[LibraryVersionRead.model_validate(asdict(row)) for row in rows[: page.limit]],
        next_cursor=page.next_uuid(rows[page.limit - 1].id, scope=scope)
        if len(rows) > page.limit
        else None,
    )


@router.get(
    "/{item_id}/versions/{version_id}",
    response_model=LibraryPublicRead,
    operation_id="getLibraryVersion",
)
def version(item_id: UUID, version_id: UUID, tx: RequestTransaction) -> LibraryPublic:
    return call(lambda: service.public(tx, item_id, version_id))


@router.get(
    "/{item_id}/versions/{version_id}/SKILL.md",
    operation_id="downloadLibrarySkill",
    response_class=Response,
    responses={200: {"content": {"text/markdown": {"schema": {"type": "string"}}}}},
)
def download(item_id: UUID, version_id: UUID, tx: RequestTransaction) -> Response:
    value = call(lambda: service.public(tx, item_id, version_id))
    if value.kind != "SKILL":
        raise HTTPException(404, "library_not_found")
    return Response(
        value.version.content.content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="SKILL.md"',
            "X-Content-Type-Options": "nosniff",
        },
    )
