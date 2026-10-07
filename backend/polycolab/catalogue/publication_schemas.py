"""Live publication envelopes, separate from immutable release encodings."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from polycolab.app.schemas import ApiModel
from polycolab.artifacts.contracts import PublishedArtifactVersionRead
from polycolab.catalogue.schemas import CatalogueRequest
from polycolab.research.activity_schemas import (
    ResearchCommentVersionRead,
    ResearchProgressVersionRead,
    ResearchSummaryVersionRevisionRead,
)
from polycolab.research.contracts import PublicationConfirm, PublicationSelection
from polycolab.research.review_schemas import ReviewRead
from polycolab.research.version_schemas import ObjectVersionRead, ObjectVersionRelationshipRead


class PublicationVersionSelection(CatalogueRequest):
    review_ids: list[UUID] = Field(
        default_factory=list, max_length=64, exclude_if=lambda value: not value
    )
    project_id: UUID
    object_version_ids: list[UUID] = Field(min_length=1, max_length=64)
    summary_revision_ids: list[UUID] = Field(default_factory=list, max_length=32)
    comment_ids: list[UUID] = Field(default_factory=list, max_length=64)
    progress_ids: list[UUID] = Field(default_factory=list, max_length=64)
    relation_ids: list[UUID] = Field(default_factory=list, max_length=64)
    artifact_ids: list[UUID] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def unique_members(self) -> PublicationVersionSelection:
        self.historical_selection()
        return self

    def historical_selection(self) -> PublicationSelection:
        fields = set(PublicationSelection.model_fields) - {"revision_ids"}
        return PublicationSelection.model_validate(
            {
                **self.model_dump(include=fields),
                "revision_ids": self.object_version_ids,
            }
        )


class PublicationVersionConfirm(PublicationVersionSelection):
    preview_digest: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=1, max_length=4000)

    def historical_command(self) -> PublicationConfirm:
        return PublicationConfirm(
            **self.historical_selection().model_dump(),
            preview_digest=self.preview_digest,
            reason=self.reason,
        )


class PublicationVersionFields(ApiModel):
    reviews: list[ReviewRead] = Field(default_factory=list)
    object_versions: list[ObjectVersionRead]
    summaries: list[ResearchSummaryVersionRevisionRead]
    comments: list[ResearchCommentVersionRead]
    progress: list[ResearchProgressVersionRead]
    relationships: list[ObjectVersionRelationshipRead]
    artifacts: list[PublishedArtifactVersionRead]


class PublicationVersionPreview(ApiModel):
    selection: PublicationVersionSelection
    required_object_version_ids: list[UUID]
    public_fields: PublicationVersionFields
    preview_digest: str


class PublicationVersionManifestRead(PublicationVersionPreview):
    id: UUID
    project_id: UUID
    publisher_display_name: str | None
    created_at: datetime


class PublicPublicationVersionSelection(ApiModel):
    review_ids: list[UUID] = Field(default_factory=list)
    object_version_ids: list[UUID]
    summary_revision_ids: list[UUID]
    comment_ids: list[UUID]
    progress_ids: list[UUID]
    relation_ids: list[UUID]
    artifact_ids: list[UUID]


class PublicPublicationVersionManifestRead(ApiModel):
    id: UUID
    preview_digest: str
    selection: PublicPublicationVersionSelection
    required_object_version_ids: list[UUID]
    public_fields: PublicationVersionFields
    publisher_display_name: str | None
    created_at: datetime


class PublicationVersionManifestPage(ApiModel):
    items: list[PublicationVersionManifestRead]
    next_cursor: str | None


def version_envelope(value: ApiModel, fields: PublicationVersionFields) -> dict[str, object]:
    """Build the live response without mutating frozen facts or their digest."""
    result = value.model_dump()
    selection = result["selection"]
    selection["object_version_ids"] = selection.pop("revision_ids")
    result["required_object_version_ids"] = result.pop("required_revision_ids")
    result["public_fields"] = fields
    return result
