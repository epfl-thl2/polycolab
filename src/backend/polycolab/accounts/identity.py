"""Canonical application identity synchronization."""

from uuid import UUID

from polycolab.accounts.names import normalized_email
from polycolab.entities.accounts import Principal, User
from polycolab.transaction import Transaction


def current_user(transaction: Transaction, principal: Principal) -> User:
    """Synchronize display claims; issuer and subject remain the identity key."""
    user = transaction.accounts.user_by_subject(principal.issuer, principal.subject)
    email = normalized_email(principal.email) if principal.email is not None else None
    if user is None:
        user = transaction.accounts.create_user(
            issuer=principal.issuer,
            subject=principal.subject,
            email=email,
            display_name=principal.display_name,
        )
    else:
        user = transaction.accounts.update_display_claims(
            user.id, email=email, display_name=principal.display_name
        )
    if user.username is None and principal.issuer == "polycolab-local":
        account = transaction.accounts.local_account(UUID(principal.subject))
        if account is not None:
            user = transaction.accounts.set_username(user.id, account.username) or user
    transaction.commit()
    return user
