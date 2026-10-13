"""Live exact-version references, separate from historical endorsement receipts."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from polycolab.app.schemas import ApiModel
from polycolab.catalogue.schemas import CatalogueRequest
from polycolab.entities.enums import CorrespondenceStatus
from polycolab.research.contracts import CorrespondenceWrite, EndorsementWrite


class ObjectVersionEndorsementWrite(CatalogueRequest):
    project_id: UUID | None = None
    object_version_id: UUID
    active: bool
    rationale: str = Field(min_length=1, max_length=4000)

    def historical_command(self) -> EndorsementWrite:
        return EndorsementWrite(
            **self.model_dump(exclude={"object_version_id"}), revision_id=self.object_version_id
        )


class ObjectVersionCorrespondenceWrite(CatalogueRequest):
    project_id: UUID | None = None
    object_version_id: UUID
    statement_object_version_id: UUID
    status: CorrespondenceStatus
    rationale: str = Field(min_length=1, max_length=4000)

    def historical_command(self) -> CorrespondenceWrite:
        return CorrespondenceWrite(
            **self.model_dump(exclude={"object_version_id", "statement_object_version_id"}),
            revision_id=self.object_version_id,
            statement_revision_id=self.statement_object_version_id,
        )


class ObjectVersionEndorsementRead(ApiModel):
    id: UUID
    object_version_id: UUID = Field(validation_alias="revision_id")
    author_username: str | None = None
    active: bool
    rationale: str
    author_display_name: str | None
    created_at: datetime


class ObjectVersionCorrespondenceRead(ApiModel):
    id: UUID
    object_version_id: UUID = Field(validation_alias="revision_id")
    statement_object_version_id: UUID = Field(validation_alias="statement_revision_id")
    author_username: str | None = None
    status: CorrespondenceStatus
    rationale: str
    author_display_name: str | None
    created_at: datetime


class ObjectVersionAssuranceRead(ApiModel):
    object_version_id: UUID = Field(validation_alias="revision_id")
    endorsements: list[ObjectVersionEndorsementRead]
    correspondence: list[ObjectVersionCorrespondenceRead]
    next_cursor: str | None = None


class ObjectVersionCurrentAssuranceRead(ObjectVersionAssuranceRead):
    next_cursor: str | None
