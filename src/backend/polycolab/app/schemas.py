"""HTTP schemas owned by the app capability."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


def workspace_field_name(name: str) -> str:
    """Expose workspace terminology while retaining historical model_dump keys."""
    return {"project_id": "workspace_id", "project_ids": "workspace_ids"}.get(name, name)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, alias_generator=workspace_field_name, populate_by_name=True
    )


class RequestModel(BaseModel):
    """Request boundary that rejects caller-supplied authority fields."""

    model_config = ConfigDict(
        extra="forbid", alias_generator=workspace_field_name, populate_by_name=True
    )


__all__ = [
    "ApiModel",
    "RequestModel",
]
