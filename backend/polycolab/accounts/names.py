"""Application account-name and email normalization."""

import re

_USERNAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,79}$")


def normalize_username(value: str) -> str:
    username = value.strip().casefold()
    if not _USERNAME.fullmatch(username):
        raise ValueError("username must be 3-80 lowercase letters, numbers, '.', '_' or '-'")
    return username


def normalized_email(email: str) -> str:
    normalized = email.strip().casefold()
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise ValueError("invalid email")
    return normalized
