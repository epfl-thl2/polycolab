"""Application transaction boundary shared across capability stores."""

from contextlib import AbstractContextManager
from types import TracebackType
from typing import Protocol, Self

from polycolab.accounts.store import AccountStore
from polycolab.artifacts.store import ArtifactStore
from polycolab.projects.store import ProjectStore


class PersistenceError(Exception):
    """Persistence adapter failure without a SQL-specific application dependency."""


class PersistenceConflict(PersistenceError):
    """A database integrity constraint rejected an application mutation."""


class Transaction(Protocol):
    @property
    def artifacts(self) -> ArtifactStore: ...

    @property
    def accounts(self) -> AccountStore: ...

    @property
    def projects(self) -> ProjectStore: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def savepoint(self) -> AbstractContextManager[None]: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class TransactionFactory(Protocol):
    def __call__(self) -> Transaction: ...
