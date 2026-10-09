"""Live activity contracts, separate from frozen publication and retry models."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from polycolab.app.schemas import ApiModel
from polycolab.catalogue.schemas import CatalogueRequest
from polycolab.entities.enums import ResearchProgressStatus
from polycolab.research.contracts import ResearchSummaryWrite


class ResearchSummaryVersionWrite(CatalogueRequest):
    project_id: UUID | None = None
    base_revision_id: UUID | None = None
    body_md: str = Field(min_length=1, max_length=100_000)
    source_object_version_ids: list[UUID] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def unique_sources(self) -> ResearchSummaryVersionWrite:
        if len(self.source_object_version_ids) != len(set(self.source_object_version_ids)):
            raise ValueError("duplicate summary sources")
        return self

    def historical_command(self) -> ResearchSummaryWrite:
        return ResearchSummaryWrite(
            project_id=self.project_id,
            base_revision_id=self.base_revision_id,
            body_md=self.body_md,
            source_revision_ids=self.source_object_version_ids,
        )


class AgentSummaryVersionWrite(ResearchSummaryVersionWrite):
    object_id: UUID


class ResearchSummaryVersionRevisionRead(ApiModel):
    id: UUID
    object_id: UUID
    number: int
    base_revision_id: UUID | None
    body_md: str
    source_object_version_ids: list[UUID] = Field(validation_alias="source_revision_ids")
    fresh: bool
    author_display_name: str | None
    actor_kind: str
    agent_display_name: str | None
    created_at: datetime


class ResearchSummaryVersionRead(ApiModel):
    object_id: UUID
    owner_display_name: str | None
    current_revision: ResearchSummaryVersionRevisionRead


class ResearchSummaryVersionPage(ApiModel):
    items: list[ResearchSummaryVersionRevisionRead]
    next_cursor: str | None


class ResearchCommentVersionWrite(CatalogueRequest):
    project_id: UUID | None = None
    object_version_id: UUID
    body_md: str = Field(min_length=1, max_length=50_000)


class ResearchProgressVersionWrite(CatalogueRequest):
    project_id: UUID | None = None
    object_version_id: UUID
    status: ResearchProgressStatus
    detail_md: str = Field(min_length=1, max_length=20_000)


class AgentObjectVersionProgress(ResearchProgressVersionWrite):
    object_id: UUID


class ActivityVersionRead(ApiModel):
    id: UUID
    object_id: UUID
    # Internal activity results and immutable rows retain their historical name.
    object_version_id: UUID = Field(validation_alias="revision_id")
    author_display_name: str | None
    actor_kind: str
    agent_display_name: str | None
    created_at: datetime


class ResearchCommentVersionRead(ActivityVersionRead):
    body_md: str


class ResearchProgressVersionRead(ActivityVersionRead):
    status: ResearchProgressStatus
    detail_md: str


class ResearchCommentVersionPage(ApiModel):
    items: list[ResearchCommentVersionRead]
    next_cursor: str | None


class ResearchProgressVersionPage(ApiModel):
    items: list[ResearchProgressVersionRead]
    next_cursor: str | None
