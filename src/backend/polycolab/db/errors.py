"""Translate SQL-specific failures at the persistence boundary."""

from collections.abc import Callable
from functools import wraps

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from polycolab.transaction import PersistenceConflict, PersistenceError


def persistence_boundary[**P, T](operation: Callable[P, T]) -> Callable[P, T]:
    @wraps(operation)
    def call(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return operation(*args, **kwargs)
        except IntegrityError as error:
            raise PersistenceConflict from error
        except SQLAlchemyError as error:
            raise PersistenceError from error

    return call
