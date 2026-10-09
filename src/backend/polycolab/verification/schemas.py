"""HTTP schemas owned by the verification capability."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from polycolab.app.schemas import ApiModel
from polycolab.entities.enums import VerificationLanguage
from polycolab.verification.contracts import ResourceLimits


class VerificationEnvironmentRead(ApiModel):
    id: UUID
    language: VerificationLanguage
    image_digest: str
    toolchain_version: str
    dependency_lock_digest: str
    build_digest: str
    platform_identity: str
    limits: ResourceLimits
    created_at: datetime
    availability_changed_at: datetime


class VerificationEnvironmentPage(ApiModel):
    items: list[VerificationEnvironmentRead]
    next_after: UUID | None


__all__ = [
    "VerificationEnvironmentRead",
    "VerificationEnvironmentPage",
]
