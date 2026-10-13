"""Claim a public username without changing the authentication identity."""

from uuid import UUID

from polycolab.accounts.names import normalize_username
from polycolab.entities.accounts import User
from polycolab.transaction import PersistenceConflict, Transaction


class UsernameConflict(Exception):
    pass


def choose_username(transaction: Transaction, user_id: UUID, username: str) -> User:
    username = normalize_username(username)
    try:
        transaction.accounts.lock_registry()
        user = transaction.accounts.user(user_id)
        if user is None:
            raise UsernameConflict
        if user.username == username:
            return user
        if (
            user.username is not None
            or transaction.accounts.user_by_username(username) is not None
            or transaction.accounts.local_account_by_username(username) is not None
        ):
            raise UsernameConflict
        selected = transaction.accounts.set_username(user.id, username)
        if selected is None:
            raise UsernameConflict
        transaction.commit()
        return selected
    except PersistenceConflict:
        transaction.rollback()
        raise UsernameConflict from None
