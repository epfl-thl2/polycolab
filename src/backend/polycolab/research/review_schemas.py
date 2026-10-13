"""Exact-version assessments; neither authorship nor formal success is caller supplied."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from polycolab.app.schemas import ApiModel, RequestModel

ReviewOutcome = Literal["REVIEWED", "SUPPORTS", "ISSUES_FOUND", "INCONCLUSIVE"]


class ReviewWrite(RequestModel):
    object_version_id: UUID
    outcome: ReviewOutcome | None
    scope: str = Field(default="Whole version", min_length=1, max_length=1000)
    rationale: str = Field(default="", max_length=20000)
    evidence_object_version_ids: list[UUID] = Field(default_factory=list, max_length=64)
    withdrawn: bool = False

    @model_validator(mode="after")
    def coherent(self) -> ReviewWrite:
        if self.withdrawn != (self.outcome is None):
            raise ValueError("withdrawal requires no outcome; an assessment requires an outcome")
        if not self.scope.strip() or (
            not self.withdrawn and self.outcome != "REVIEWED" and not self.rationale.strip()
        ):
            raise ValueError("review scope and rationale cannot be blank")
        if len(set(self.evidence_object_version_ids)) != len(self.evidence_object_version_ids):
            raise ValueError("duplicate evidence versions")
        return self


class AgentReviewWrite(ReviewWrite):
    object_id: UUID
    project_id: UUID | None = None


class ReviewRead(ApiModel):
    is_mine: bool = False
    model_id: str | None = None
    id: UUID
    object_version_id: UUID
    reviewer_id: str | None = Field(default=None, exclude=True)
    actor_kind: Literal["HUMAN", "AGENT"]
    reviewer_name: str
    outcome: ReviewOutcome | None
    scope: str
    rationale: str
    evidence_object_version_ids: list[UUID]
    withdrawn: bool
    self_review: bool
    created_at: datetime


class ReviewPage(ApiModel):
    items: list[ReviewRead]
    next_cursor: str | None


class ReviewBatch(RequestModel):
    object_version_ids: list[UUID] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def unique(self) -> ReviewBatch:
        if len(set(self.object_version_ids)) != len(self.object_version_ids):
            raise ValueError("duplicate versions")
        return self


class ReviewCounts(ApiModel):
    reviewed: int = 0
    supports: int = 0
    issues_found: int = 0
    inconclusive: int = 0
    self_reviews: int = 0


class ReviewSummary(ApiModel):
    object_version_id: UUID
    human: ReviewCounts
    ai: ReviewCounts
    formal: Literal["UNAVAILABLE"] = "UNAVAILABLE"
