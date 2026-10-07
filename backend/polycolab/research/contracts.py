"""Versioned human/agent research input contracts shared by APIs and tools."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from polycolab.app.schemas import ApiModel
from polycolab.artifacts.contracts import PublishedArtifactRead
from polycolab.catalogue.schemas import (
    CatalogueRequest,
    CatalogueRevise,
    CatalogueSource,
    CatalogueVersionCreate,
)
from polycolab.entities.enums import (
    CorrespondenceStatus,
    RelationType,
    ResearchObjectKind,
    ResearchProgressStatus,
)
from polycolab.entities.object_kinds import ObjectKind
from polycolab.entities.research import KIND_DEFINITIONS
from polycolab.research.review_schemas import ReviewRead
from polycolab.research.schemas import AttemptEvidenceRead as AttemptEvidenceRead
from polycolab.research.schemas import ProofStructureRead as ProofStructureRead
from polycolab.research.schemas import (
    ProofStructureRequest,
    ResearchAttemptRequest,
    VersionContentRead,
)
from polycolab.research.schemas import ResearchAttemptStructureRead as ResearchAttemptStructureRead


class ProofStructureWrite(ProofStructureRequest):
    pass


class EndorsementWrite(CatalogueRequest):
    project_id: UUID | None = None
    revision_id: UUID
    active: bool
    rationale: str = Field(min_length=1, max_length=4000)


class EndorsementRead(ApiModel):
    id: UUID
    revision_id: UUID
    assessor_id: UUID
    active: bool
    rationale: str
    author_display_name: str | None
    created_at: datetime


class CorrespondenceWrite(CatalogueRequest):
    project_id: UUID | None = None
    revision_id: UUID
    statement_revision_id: UUID
    status: CorrespondenceStatus
    rationale: str = Field(min_length=1, max_length=4000)


class CorrespondenceRead(ApiModel):
    id: UUID
    revision_id: UUID
    statement_revision_id: UUID
    assessor_id: UUID
    status: CorrespondenceStatus
    rationale: str
    author_display_name: str | None
    created_at: datetime


class AssuranceRead(ApiModel):
    revision_id: UUID
    endorsements: list[EndorsementRead]
    correspondence: list[CorrespondenceRead]
    next_cursor: str | None = None


class AssuranceCurrentRead(ApiModel):
    revision_id: UUID
    endorsements: list[EndorsementRead]
    correspondence: list[CorrespondenceRead]
    next_cursor: str | None


class RecordWrite(CatalogueRequest):
    suggestion: CatalogueRevise | None = None
    project_id: UUID | None = None
    object_id: UUID | None = None
    base_revision_id: UUID | None = None
    kind: ResearchObjectKind
    title: str = Field(min_length=1, max_length=500)
    content_md: str = Field(min_length=1, max_length=100_000)
    assumptions_md: str = Field(default="None stated", min_length=1, max_length=20_000)
    statement_revision_ids: list[UUID] = Field(default_factory=list, max_length=32)
    reported_outcome: (
        Literal["UNASSESSED", "IN_PROGRESS", "FAILED", "PARTIAL", "SUCCEEDED"] | None
    ) = "UNASSESSED"
    explanation_md: str | None = Field(default=None, max_length=20_000)
    proof_sketch: ProofStructureWrite | None = None
    attempt: ResearchAttemptRequest | None = None
    reason: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def coherent(self) -> RecordWrite:
        if self.suggestion is not None and (
            self.project_id is not None
            or self.kind.value != "NOTE"
            or self.suggestion.base_revision_id not in self.statement_revision_ids
        ):
            raise ValueError("public corrections must be notes attached to the exact proposed base")
        if (self.object_id is None) != (self.base_revision_id is None):
            raise ValueError("editing requires an object and exact base")
        if len(set(self.statement_revision_ids)) != len(self.statement_revision_ids):
            raise ValueError("duplicate targets")
        if self.project_id is None and not self.statement_revision_ids:
            raise ValueError("public research must be attached to a statement")
        if self.object_id is None and not KIND_DEFINITIONS[self.kind].creatable:
            raise ValueError("new proof approaches must use PROOF_SKETCH")
        if (self.kind in {ResearchObjectKind.PROOF, ResearchObjectKind.PROOF_SKETCH}) != (
            self.proof_sketch is not None
        ):
            raise ValueError("proof structure is required exactly for proof-sketch records")
        if (self.kind is ResearchObjectKind.ATTEMPT) != (self.attempt is not None):
            raise ValueError("attempt structure is required exactly for attempt records")
        if self.proof_sketch is not None:
            required = {
                self.proof_sketch.conclusion_revision_id,
                *self.proof_sketch.premise_revision_ids,
            }
            if not required.issubset(self.statement_revision_ids):
                raise ValueError("proof conclusions and premises must be exact record attachments")
        return self


class SnapshotRecordWrite(RecordWrite):
    """Internal complete-snapshot command; never used to decode old receipts."""

    semantic_metadata: dict[str, object] = Field(default_factory=dict)
    change_summary: str | None
    premise_positions: list[int]
    evidence_positions: list[int]


class RecordRead(VersionContentRead):
    catalogue_entry_id: UUID | None = None
    catalogue_source: CatalogueSource | None = None
    catalogue_reported_status: str | None = None
    suggestion: CatalogueRevise | None = None
    object_id: UUID
    revision_id: UUID
    base_revision_id: UUID | None
    number: int
    kind: ResearchObjectKind
    title: str
    content_md: str
    assumptions_md: str
    statement_revision_ids: list[UUID]
    reported_outcome: str | None
    explanation_md: str | None
    proof_sketch: ProofStructureRead | None = None
    attempt: ResearchAttemptStructureRead | None = None
    author_display_name: str | None
    actor_kind: str
    author_user_id: UUID | None = None
    agent_id: UUID | None = None
    sponsor_user_id: UUID | None = None
    agent_display_name: str | None
    created_at: datetime


class RecordPage(ApiModel):
    items: list[RecordRead]
    next_cursor: str | None


class ObjectVersionDisplayRequest(CatalogueRequest):
    project_id: UUID | None = None
    object_version_ids: list[UUID] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def unique_versions(self) -> ObjectVersionDisplayRequest:
        if len(self.object_version_ids) != len(set(self.object_version_ids)):
            raise ValueError("duplicate display object version")
        return self


class ObjectVersionDisplayRead(ApiModel):
    object_version_id: UUID
    object_id: UUID
    kind: ObjectKind
    title: str


class ObjectVersionDisplayBatchRead(ApiModel):
    items: list[ObjectVersionDisplayRead]


class ResearchAttemptPage(ApiModel):
    items: list[RecordRead]
    next_cursor: str | None


class HumanNoteWrite(CatalogueRequest):
    project_id: UUID | None = None
    base_revision_id: UUID | None = None
    body_md: str = Field(min_length=1, max_length=100_000)


class HumanNoteRevisionRead(ApiModel):
    id: UUID
    object_id: UUID
    number: int
    base_revision_id: UUID | None
    body_md: str
    author_display_name: str | None
    created_at: datetime


class HumanNoteRead(ApiModel):
    object_id: UUID
    owner_user_id: UUID
    owner_display_name: str | None
    can_edit: bool
    current_revision: HumanNoteRevisionRead


class HumanNotePage(ApiModel):
    items: list[HumanNoteRevisionRead]
    next_cursor: str | None


class ResearchSummaryWrite(CatalogueRequest):
    project_id: UUID | None = None
    base_revision_id: UUID | None = None
    body_md: str = Field(min_length=1, max_length=100_000)
    source_revision_ids: list[UUID] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def unique_sources(self) -> ResearchSummaryWrite:
        if len(self.source_revision_ids) != len(set(self.source_revision_ids)):
            raise ValueError("duplicate summary sources")
        return self


class ResearchSummaryRevisionRead(ApiModel):
    id: UUID
    object_id: UUID
    number: int
    base_revision_id: UUID | None
    body_md: str
    source_revision_ids: list[UUID]
    fresh: bool
    author_display_name: str | None
    actor_kind: str
    agent_display_name: str | None
    created_at: datetime


class ResearchSummaryRead(ApiModel):
    object_id: UUID
    owner_display_name: str | None
    current_revision: ResearchSummaryRevisionRead


class ResearchSummaryPage(ApiModel):
    items: list[ResearchSummaryRevisionRead]
    next_cursor: str | None


class ResearchProgressWrite(CatalogueRequest):
    project_id: UUID | None = None
    revision_id: UUID
    status: ResearchProgressStatus
    detail_md: str = Field(min_length=1, max_length=20_000)


class ResearchProgressRead(ApiModel):
    id: UUID
    object_id: UUID
    revision_id: UUID
    status: ResearchProgressStatus
    detail_md: str
    author_display_name: str | None
    actor_kind: str
    agent_display_name: str | None
    created_at: datetime


class ResearchProgressPage(ApiModel):
    items: list[ResearchProgressRead]
    next_cursor: str | None


class ResearchCommentWrite(CatalogueRequest):
    project_id: UUID | None = None
    revision_id: UUID
    body_md: str = Field(min_length=1, max_length=50_000)


class ResearchCommentRead(ApiModel):
    id: UUID
    object_id: UUID
    revision_id: UUID
    body_md: str
    author_display_name: str | None
    actor_kind: str
    agent_display_name: str | None
    created_at: datetime


class ResearchCommentPage(ApiModel):
    items: list[ResearchCommentRead]
    next_cursor: str | None


class PublicationSelection(CatalogueRequest):
    review_ids: list[UUID] = Field(
        default_factory=list, max_length=64, exclude_if=lambda value: not value
    )
    project_id: UUID
    revision_ids: list[UUID] = Field(min_length=1, max_length=64)
    summary_revision_ids: list[UUID] = Field(default_factory=list, max_length=32)
    comment_ids: list[UUID] = Field(default_factory=list, max_length=64)
    progress_ids: list[UUID] = Field(default_factory=list, max_length=64)
    relation_ids: list[UUID] = Field(default_factory=list, max_length=64)
    artifact_ids: list[UUID] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def unique_members(self) -> PublicationSelection:
        for values in (
            self.review_ids,
            self.revision_ids,
            self.summary_revision_ids,
            self.comment_ids,
            self.progress_ids,
            self.relation_ids,
            self.artifact_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("duplicate publication member")
        return self


class PublishedRelationRead(ApiModel):
    id: UUID
    source_revision_id: UUID
    target_revision_id: UUID
    relation_type: RelationType
    rationale: str
    author_display_name: str | None
    actor_kind: str
    agent_display_name: str | None
    created_at: datetime


class PublicationFields(ApiModel):
    reviews: list[ReviewRead] = Field(default_factory=list, exclude_if=lambda value: not value)
    records: list[RecordRead]
    summaries: list[ResearchSummaryRevisionRead]
    comments: list[ResearchCommentRead]
    progress: list[ResearchProgressRead]
    relations: list[PublishedRelationRead]
    artifacts: list[PublishedArtifactRead]


class PublicationPreview(ApiModel):
    selection: PublicationSelection
    required_revision_ids: list[UUID]
    public_fields: PublicationFields
    preview_digest: str


class PublicationConfirm(PublicationSelection):
    preview_digest: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=1, max_length=4000)


class PublicationManifestRead(ApiModel):
    id: UUID
    project_id: UUID
    preview_digest: str
    selection: PublicationSelection
    required_revision_ids: list[UUID]
    public_fields: PublicationFields
    publisher_display_name: str | None
    created_at: datetime


class PublicPublicationSelection(ApiModel):
    review_ids: list[UUID] = Field(default_factory=list)
    revision_ids: list[UUID]
    summary_revision_ids: list[UUID]
    comment_ids: list[UUID]
    progress_ids: list[UUID]
    relation_ids: list[UUID]
    artifact_ids: list[UUID]


class PublicPublicationManifestRead(ApiModel):
    id: UUID
    preview_digest: str
    selection: PublicPublicationSelection
    required_revision_ids: list[UUID]
    public_fields: PublicationFields
    publisher_display_name: str | None
    created_at: datetime


class PublicationManifestPage(ApiModel):
    items: list[PublicationManifestRead]
    next_cursor: str | None


class ResearchSummaryToolWrite(ResearchSummaryWrite):
    object_id: UUID


class ResearchProgressToolWrite(ResearchProgressWrite):
    object_id: UUID


class ResearchCommentToolWrite(ResearchCommentWrite):
    object_id: UUID


class ScopedRelationWrite(CatalogueRequest):
    project_id: UUID | None = None
    source_revision_id: UUID
    target_revision_id: UUID
    relation_type: RelationType
    rationale: str = Field(min_length=1, max_length=4000)


class SnapshotRelationWrite(ScopedRelationWrite):
    description: str | None


class ScopedRelationRead(ApiModel):
    id: UUID
    source_revision_id: UUID
    target_revision_id: UUID
    relation_type: RelationType
    rationale: str


class ResourceResult(ApiModel):
    id: UUID
    revision_id: UUID | None = None


class WorkspaceCopyCreate(CatalogueRequest):
    revision_id: UUID
    project_id: UUID | None = None
    workspace_name: str = Field(default="Research workspace", min_length=1, max_length=200)
    workspace_visibility: Literal["PUBLIC", "PRIVATE"] = "PUBLIC"


class WorkspaceCopyRead(ApiModel):
    project_id: UUID
    object_id: UUID
    revision_id: UUID
    source_revision_id: UUID


class WorkspaceReferenceCreate(CatalogueRequest):
    object_version_id: UUID
    project_id: UUID | None = None
    workspace_name: str = Field(default="Research workspace", min_length=1, max_length=200)
    reason: str = Field(default="Import from Library", min_length=1, max_length=4000)
    workspace_visibility: Literal["PUBLIC", "PRIVATE"] = "PUBLIC"
    create_new_workspace: bool | None = None

    @model_validator(mode="after")
    def explicit_destination(self) -> WorkspaceReferenceCreate:
        if self.create_new_workspace and self.project_id:
            raise ValueError("choose an existing workspace or create a new one")
        return self


class WorkspaceReferenceUpgrade(CatalogueRequest):
    expected_current_reference_version_id: UUID
    object_version_id: UUID
    reason: str = Field(min_length=1, max_length=4000)


class WorkspaceReferenceRead(ApiModel):
    id: UUID
    project_id: UUID
    object_id: UUID
    reference_version_id: UUID
    number: int
    previous_reference_version_id: UUID | None
    object_version_id: UUID
    available: bool
    title: str | None
    reason: str
    created_at: datetime
    latest_object_version_id: UUID | None = None


class WorkspaceReferencePage(ApiModel):
    items: list[WorkspaceReferenceRead]
    next_cursor: str | None


class CorrectionDecisionWrite(CatalogueRequest):
    action: Literal["ACCEPT", "EDIT_AND_ACCEPT", "REJECT"]
    edited: CatalogueVersionCreate | None = None
    reason: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def coherent(self) -> CorrectionDecisionWrite:
        if (self.action == "EDIT_AND_ACCEPT") != (self.edited is not None):
            raise ValueError("edited formulation is required only for edit-and-accept")
        return self


class CorrectionDecisionRead(ApiModel):
    suggestion_object_version_id: UUID
    action: str
    decided_object_version_id: UUID | None
    reason: str


class DiscoveryHit(ApiModel):
    record: RecordRead
    catalogue_entry_id: UUID | None
    source_identifier: str | None
    source_version: str | None
    source_locator: str | None
    catalogue_status: str | None


class DiscoveryPage(ApiModel):
    items: list[DiscoveryHit]
    next_cursor: str | None


class CommunityToggle(CatalogueRequest):
    active: bool


class CommunityState(ApiModel):
    following: bool
    interested: bool
    interest_count: int


class PublicCommunityState(ApiModel):
    interest_count: int


class RecordModerationWrite(CatalogueRequest):
    expected_current_object_version_id: UUID
    hidden: bool
    reason: str = Field(min_length=1, max_length=4000)


class RecordModerationRead(ApiModel):
    id: UUID
    object_id: UUID
    object_version_id: UUID
    actor_user_id: UUID
    hidden: bool
    reason: str
    created_at: datetime


class ResearchNotificationRead(ApiModel):
    id: UUID
    entry_id: UUID
    object_version_id: UUID
    created_at: datetime


class ResearchNotificationPage(ApiModel):
    items: list[ResearchNotificationRead]
    next_cursor: str | None


class ProgressSummaryItem(ApiModel):
    object_version_id: UUID
    title: str
    excerpt: str
    reported_outcome: str | None


class ProgressSummaryRead(ApiModel):
    entry_id: UUID
    state: Literal["PENDING", "READY"]
    inputs_digest: str | None
    items: list[ProgressSummaryItem]
    status_counts: dict[str, int]
