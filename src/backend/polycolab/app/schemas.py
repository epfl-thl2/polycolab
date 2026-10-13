"""HTTP schemas owned by the app capability."""

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RequestModel(BaseModel):
    """Request boundary that rejects caller-supplied authority and obsolete fields."""

    model_config = ConfigDict(extra="forbid")


__all__ = ["ApiModel", "RequestModel"]
