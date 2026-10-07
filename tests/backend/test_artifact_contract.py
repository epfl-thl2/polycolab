from typing import Any

import pytest
from pydantic import ValidationError

from polycolab.artifacts.contracts import ArtifactUploadDeclaration, private_download_headers
from polycolab.artifacts.storage import MAX_ARTIFACT_BYTES


@pytest.mark.parametrize(
    "overrides",
    [
        {"sha256": "a" * 64 + "\n"},
        {"sha256": "A" * 64},
        {"byte_length": True},
        {"byte_length": "5"},
        {"byte_length": -1},
        {"byte_length": MAX_ARTIFACT_BYTES + 1},
        {"media_type": "text/html\r\nX-Injected: value"},
        {"media_type": "text/plain; filename=private-secret"},
        {"storage_key": "private-key"},
        {"author_id": "forged-actor"},
        {"filename": "private-secret.html"},
    ],
)
def test_untrusted_declaration_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ArtifactUploadDeclaration.model_validate(
            {"sha256": "a" * 64, "byte_length": 5, **overrides}
        )


def test_active_content_mime_is_metadata_only() -> None:
    declaration = ArtifactUploadDeclaration(sha256="a" * 64, byte_length=5, media_type="text/html")
    assert declaration.integrity().byte_length == 5
    headers = private_download_headers()
    assert headers["Content-Type"] == "application/octet-stream"
    assert headers["Content-Disposition"] == 'attachment; filename="artifact.bin"'
    assert headers["Cache-Control"] == "private, no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Content-Security-Policy"] == "default-src 'none'; sandbox"
    assert "Location" not in headers
