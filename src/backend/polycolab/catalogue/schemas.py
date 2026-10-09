"""HTTP schemas owned by the catalogue capability."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from polycolab.app.schemas import ApiModel, RequestModel


class CatalogueRequest(RequestModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CatalogueSource(CatalogueRequest):
    identifier: str = Field(min_length=1, max_length=2000)
    version: str = Field(min_length=1, max_length=500)
    locator: str = Field(min_length=1, max_length=1000)


class CatalogueFormulation(CatalogueRequest):
    title: str = Field(min_length=1, max_length=500)
    content_md: str = Field(min_length=1, max_length=100_000)
    assumptions_md: str = Field(min_length=1, max_length=20_000)
    source: CatalogueSource | None = None
    review_rationale: str | None = Field(default=None, min_length=1, max_length=4000)
    reported_status: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def supported_status(self) -> CatalogueFormulation:
        if self.source is None and not self.review_rationale:
            raise ValueError("a literature source or human review rationale is required")
        return self


class CatalogueAdmit(CatalogueFormulation):
    kind: Literal["PROBLEM", "DEFINITION", "CLAIM"]


class CatalogueRevise(CatalogueFormulation):
    base_revision_id: UUID


class CatalogueVersionCreate(CatalogueFormulation):
    expected_current_object_version_id: UUID


class CataloguePromote(CatalogueRequest):
    revision_id: UUID
    source: CatalogueSource
    reported_status: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)


class CatalogueModerate(CatalogueRequest):
    base_revision_id: UUID
    action: Literal["HIDE", "RESTORE"]
    reason: str = Field(min_length=1, max_length=4000)


class CataloguePromotionWrite(CatalogueRequest):
    object_version_id: UUID
    source: CatalogueSource
    reported_status: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)


class CatalogueModerationWrite(CatalogueRequest):
    expected_current_object_version_id: UUID
    action: Literal["HIDE", "RESTORE"]
    reason: str = Field(min_length=1, max_length=4000)


class CatalogueModeratorUpdate(CatalogueRequest):
    active: bool
    reason: str = Field(min_length=1, max_length=4000)


class CatalogueMutationRead(ApiModel):
    entry_id: UUID
    revision_id: UUID


class PublicStatementRead(ApiModel):
    object_id: UUID
    revision_id: UUID
    kind: Literal["PROBLEM", "DEFINITION", "CLAIM"]
    title: str
    content_md: str
    assumptions_md: str
    author_display_name: str | None


class CatalogueAuditRead(ApiModel):
    id: UUID
    object_version_id: UUID
    action: str
    reason: str
    actor_user_id: UUID
    created_at: datetime


__all__ = [
    "CatalogueRequest",
    "CatalogueSource",
    "CatalogueFormulation",
    "CatalogueAdmit",
    "CatalogueRevise",
    "CatalogueVersionCreate",
    "CataloguePromote",
    "CatalogueModerate",
    "CataloguePromotionWrite",
    "CatalogueModerationWrite",
    "CatalogueModeratorUpdate",
    "CatalogueMutationRead",
    "PublicStatementRead",
    "CatalogueAuditRead",
]


class CatalogueObjectAdmit(CatalogueFormulation):
    kind: Literal["PROBLEM", "DEFINITION", "STATEMENT"]

    def historical_command(self) -> CatalogueAdmit:
        values = self.model_dump()
        values["kind"] = "CLAIM" if self.kind == "STATEMENT" else self.kind
        return CatalogueAdmit.model_validate(values)
