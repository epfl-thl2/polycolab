"""Invitation-secret delivery boundary for local development and deployments."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class InvitationDeliveryUnavailable(Exception):
    pass


class InvitationDelivery(Protocol):
    def deliver(self, invitation_id: UUID, recipient_email: str, token: str) -> None: ...

    def retract(self, invitation_id: UUID) -> None: ...


class LocalInvitationOutbox:
    """Ephemeral local delivery; no HTTP route serializes this secret store."""

    def __init__(self) -> None:
        self._tokens: dict[UUID, str] = {}

    def deliver(self, invitation_id: UUID, recipient_email: str, token: str) -> None:
        del recipient_email
        self._tokens[invitation_id] = token

    def retract(self, invitation_id: UUID) -> None:
        self._tokens.pop(invitation_id, None)

    def token_for_development(self, invitation_id: UUID) -> str | None:
        return self._tokens.get(invitation_id)


class UnconfiguredInvitationDelivery:
    """Fail closed so staging/production never create an undeliverable invitation."""

    def deliver(self, invitation_id: UUID, recipient_email: str, token: str) -> None:
        del invitation_id, recipient_email, token
        raise InvitationDeliveryUnavailable

    def retract(self, invitation_id: UUID) -> None:
        del invitation_id
