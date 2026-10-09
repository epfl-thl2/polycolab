"""HTTP schemas owned by the accounts capability."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr

from polycolab.app.schemas import ApiModel, RequestModel


class UserRead(ApiModel):
    id: UUID
    display_name: str | None
    email: str | None


class AccountEmailRead(ApiModel):
    verified_email: str | None
    verified_at: datetime | None
    pending_email: str | None
    pending_requested_at: datetime | None


class AccountEmailChange(RequestModel):
    email: str = Field(min_length=3, max_length=320)


class AccountRecoveryTokenRequest(RequestModel):
    token: SecretStr = Field(min_length=32, max_length=256)


class PasswordResetRequest(RequestModel):
    email: str = Field(min_length=3, max_length=320)


class PasswordResetConfirm(AccountRecoveryTokenRequest):
    password: SecretStr = Field(min_length=12, max_length=256)


class RecoveryAccepted(ApiModel):
    accepted: Literal[True] = True


__all__ = [
    "UserRead",
    "AccountEmailRead",
    "AccountEmailChange",
    "AccountRecoveryTokenRequest",
    "PasswordResetRequest",
    "PasswordResetConfirm",
    "RecoveryAccepted",
]
