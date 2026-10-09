"""Shared FastAPI dependencies and pagination primitives."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Generator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor
from polycolab.accounts.authentication import CurrentPrincipal, human_actor_from_verified_principal
from polycolab.accounts.identity import current_user
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.accounts import User
from polycolab.transaction import Transaction


def session_for_request(request: Request) -> Generator[Session]:
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
    finally:
        session.close()


DbSession = Annotated[Session, Depends(session_for_request)]


def transaction_for_request(session: DbSession) -> Transaction:
    """Share the request transaction with all capability stores."""
    return SqlAlchemyTransaction(session)


RequestTransaction = Annotated[Transaction, Depends(transaction_for_request)]


def authenticated_user(session: DbSession, principal: CurrentPrincipal) -> User:
    return current_user(SqlAlchemyTransaction(session), principal)


CurrentUser = Annotated[User, Depends(authenticated_user)]


def authenticated_actor(session: DbSession, principal: CurrentPrincipal) -> Actor:
    user = current_user(SqlAlchemyTransaction(session), principal)
    return human_actor_from_verified_principal(principal=principal, user_id=user.id)


CurrentActor = Annotated[Actor, Depends(authenticated_actor)]


@dataclass(frozen=True)
class PageRequest:
    limit: int
    offset: int


def page_request(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
) -> PageRequest:
    """Decode an opaque offset cursor for deterministic bounded listings."""

    if cursor is None:
        return PageRequest(limit=limit, offset=0)
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")
        prefix, raw_offset = decoded.split(":", maxsplit=1)
        offset = int(raw_offset)
        if prefix != "v1" or offset < 0:
            raise ValueError
    except binascii.Error, UnicodeError, ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from None
    return PageRequest(limit=limit, offset=offset)


Page = Annotated[PageRequest, Depends(page_request)]


def paginated[T](items: list[T], page: PageRequest, response: Response) -> list[T]:
    selected = items[page.offset : page.offset + page.limit]
    response.headers["X-Total-Count"] = str(len(items))
    if page.offset + page.limit < len(items):
        response.headers["X-Next-Cursor"] = base64.urlsafe_b64encode(
            f"v1:{page.offset + page.limit}".encode("ascii")
        ).decode("ascii")
    return selected


__all__ = ["CurrentActor", "CurrentUser", "DbSession", "Page", "PageRequest", "paginated"]
