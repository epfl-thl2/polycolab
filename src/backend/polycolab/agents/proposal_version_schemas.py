"""Version-based proposal commands; historical stored payloads decode separately.

Proposal/run ownership determines the destination. A change cannot nominate a
different workspace, Library destination, author, or contribution identity.
These contracts are the input foundation for the coordinated proposal cutover;
they do not replace the historical decoder in ``proposals.py``.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter

from polycolab.app.schemas import ApiModel, RequestModel
from polycolab.research.version_schemas import (
    AttemptVersionContentRead,
    EditableVersionSnapshot,
    ObjectVersionCommentCreate,
    ObjectVersionCreate,
    ObjectVersionRelationshipInput,
    OrdinaryKind,
    ProofVersionContentRead,
    StructuralRelationshipInput,
    VersionContentRead,
)


class ProposeObjectCreate(RequestModel):
    kind: Literal["CREATE_OBJECT"]
    snapshot: EditableVersionSnapshot


class ProposeObjectVersionCreate(ObjectVersionCreate):
    kind: Literal["CREATE_OBJECT_VERSION"]
    object_id: UUID


class ProposeRelationshipCreate(RequestModel):
    kind: Literal["CREATE_RELATIONSHIP"]
    relationship: ObjectVersionRelationshipInput


class ProposeCommentCreate(ObjectVersionCommentCreate):
    kind: Literal["CREATE_COMMENT"]
    object_id: UUID


ObjectVersionProposalChange = Annotated[
    ProposeObjectCreate
    | ProposeObjectVersionCreate
    | ProposeRelationshipCreate
    | ProposeCommentCreate,
    Field(discriminator="kind"),
]

proposal_change_adapter: TypeAdapter[ObjectVersionProposalChange] = TypeAdapter(
    ObjectVersionProposalChange
)


class ObjectVersionProposalSubmit(RequestModel):
    summary: str = Field(min_length=1, max_length=20_000)
    changes: list[ObjectVersionProposalChange] = Field(min_length=1, max_length=100)


class ProposalSnapshotReadBase(ApiModel):
    structural_relationships: list[StructuralRelationshipInput]
    change_summary: str | None


class OrdinaryProposalSnapshotRead(ProposalSnapshotReadBase):
    kind: OrdinaryKind
    content: VersionContentRead


class ProofProposalSnapshotRead(ProposalSnapshotReadBase):
    kind: Literal["PROOF"]
    content: ProofVersionContentRead


class AttemptProposalSnapshotRead(ProposalSnapshotReadBase):
    kind: Literal["ATTEMPT"]
    content: AttemptVersionContentRead


ProposalSnapshotRead = Annotated[
    OrdinaryProposalSnapshotRead | ProofProposalSnapshotRead | AttemptProposalSnapshotRead,
    Field(discriminator="kind"),
]


class ProposedObjectRead(ApiModel):
    kind: Literal["CREATE_OBJECT"]
    snapshot: ProposalSnapshotRead


class ProposedObjectVersionRead(ApiModel):
    kind: Literal["CREATE_OBJECT_VERSION"]
    object_id: UUID
    expected_current_object_version_id: UUID
    snapshot: ProposalSnapshotRead


ObjectVersionProposalPayloadRead = Annotated[
    ProposedObjectRead
    | ProposedObjectVersionRead
    | ProposeRelationshipCreate
    | ProposeCommentCreate,
    Field(discriminator="kind"),
]
