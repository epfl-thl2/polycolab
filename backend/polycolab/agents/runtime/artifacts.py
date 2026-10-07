"""Host/guest export declarations; no storage keys, credentials or publication authority."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from polycolab.verification.contracts import RelativePath, validate_path


class ExportDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: RelativePath
    display_name: str = Field(min_length=1, max_length=200)
    media_type: str = Field(
        default="application/octet-stream",
        pattern=r"^[a-zA-Z0-9!#$&^_.+-]+/[a-zA-Z0-9!#$&^_.+-]+$",
        max_length=127,
    )
    _path = field_validator("path")(validate_path)


EXPORT_TOOL = {
    "type": "function",
    "function": {
        "name": "export_artifact",
        "description": (
            "Register a file written under /outputs as a private downloadable session artifact. "
            "Only explicitly registered files survive a successful turn. "
            "The path is relative to /outputs. This does not publish or verify research."
        ),
        "parameters": ExportDeclaration.model_json_schema(),
    },
}


class UploadRequest(ExportDeclaration):
    worker_id: str = Field(min_length=1, max_length=200)
    lease_generation: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(ge=0, le=16 * 1024**2)
