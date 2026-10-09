"""Filter-bound SQL keyset pagination; never materialize an unbounded collection."""

import base64
import binascii
import hashlib
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Integer
from sqlalchemy.orm import Session


class Collection[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


@dataclass(frozen=True)
class CursorPage:
    limit: int
    cursor: str | None

    def after_uuid(self, *, scope: str) -> UUID | None:
        if not self.cursor:
            return None
        try:
            version, bound, value = (
                base64.urlsafe_b64decode(self.cursor.encode()).decode().split(":")
            )
            if version != "v2" or bound != hashlib.sha256(scope.encode()).hexdigest()[:24]:
                raise ValueError
            return UUID(value)
        except ValueError, UnicodeError, binascii.Error:
            raise HTTPException(422, "invalid_cursor") from None

    def next_uuid(self, value: UUID, *, scope: str) -> str:
        digest = hashlib.sha256(scope.encode()).hexdigest()[:24]
        return base64.urlsafe_b64encode(f"v2:{digest}:{value}".encode()).decode()

    def select(
        self,
        session: Session,
        statement: Any,
        column: Any,
        *,
        scope: str,
        scalars: bool = True,
        descending: bool = False,
    ) -> tuple[list[Any], str | None]:
        digest = hashlib.sha256(scope.encode()).hexdigest()[:24]
        if self.cursor:
            try:
                version, bound, value = (
                    base64.urlsafe_b64decode(self.cursor.encode()).decode().split(":")
                )
                if version != "v2" or bound != digest:
                    raise ValueError
                after = int(value) if isinstance(column.type, Integer) else UUID(value)
            except ValueError, UnicodeError, binascii.Error:
                raise HTTPException(422, "invalid_cursor") from None
            statement = statement.where(column < after if descending else column > after)
        bounded = statement.order_by(column.desc() if descending else column).limit(self.limit + 1)
        rows = list(session.scalars(bounded) if scalars else session.execute(bounded))
        more = len(rows) > self.limit
        rows = rows[: self.limit]
        cursor = (
            base64.urlsafe_b64encode(
                f"v2:{digest}:{getattr(rows[-1], column.key)}".encode()
            ).decode()
            if more
            else None
        )
        return rows, cursor


def cursor_page(
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
) -> CursorPage:
    return CursorPage(limit, cursor)


Pagination = Annotated[CursorPage, Depends(cursor_page)]
