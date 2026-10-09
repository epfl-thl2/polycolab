"""SQLAlchemy implementation of the shared application transaction boundary."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Self

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from polycolab.db.errors import persistence_boundary
from polycolab.db.stores.accounts import SqlAccountStore
from polycolab.db.stores.artifacts import SqlArtifactStore
from polycolab.db.stores.workspaces import SqlWorkspaceStore
from polycolab.transaction import PersistenceConflict, PersistenceError, TransactionFactory


class SqlAlchemyTransaction:
    def __init__(self, session: Session, *, close_on_exit: bool = False) -> None:
        self._session = session
        self._close_on_exit = close_on_exit
        self.accounts = SqlAccountStore(session)
        self.artifacts = SqlArtifactStore(session)
        self.workspaces = SqlWorkspaceStore(session)

    @persistence_boundary
    def commit(self) -> None:
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    @persistence_boundary
    def rollback(self) -> None:
        self._session.rollback()

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        try:
            with self._session.begin_nested():
                yield
        except IntegrityError as error:
            raise PersistenceConflict from error
        except SQLAlchemyError as error:
            raise PersistenceError from error

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self.rollback()
        finally:
            if self._close_on_exit:
                self._session.close()


def make_transaction_factory(session_factory: Callable[[], Session]) -> TransactionFactory:
    def create() -> SqlAlchemyTransaction:
        return SqlAlchemyTransaction(session_factory(), close_on_exit=True)

    return create
