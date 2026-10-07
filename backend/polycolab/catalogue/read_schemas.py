"""Live catalogue views; immutable release decoders remain in schemas."""

from datetime import datetime
from uuid import UUID

from polycolab.app.schemas import ApiModel
from polycolab.catalogue.schemas import CatalogueSource
from polycolab.research.version_schemas import ObjectVersionRead


class CatalogueVersionMutationRead(ApiModel):
    entry_id: UUID
    object_version_id: UUID


class PublicCatalogueRead(ApiModel):
    entry_id: UUID
    object_version: ObjectVersionRead
    source: CatalogueSource | None
    reported_status: str
    admitted_at: datetime
    review_rationale: str | None = None
    reviewer_display_name: str | None = None
    reviewed_at: datetime | None = None


class PublicCataloguePage(ApiModel):
    items: list[PublicCatalogueRead]
    next_cursor: str | None
