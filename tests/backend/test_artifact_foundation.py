import pytest
from pydantic import ValidationError

from polycolab.platform.config import Settings


def test_artifact_settings_require_complete_explicit_storage_authority() -> None:
    assert not Settings().artifact_storage_configured
    with pytest.raises(ValidationError, match="artifact endpoint"):
        Settings(artifact_s3_bucket="incomplete")
    configured = Settings.model_validate(
        {
            "artifact_s3_endpoint": "http://127.0.0.1:3900",
            "artifact_s3_bucket": "polycolab-test",
            "artifact_s3_region": "garage",
            "artifact_s3_access_key": "access",
            "artifact_s3_secret_key": "top-secret-value",
        }
    )
    assert configured.artifact_s3_endpoint is not None
    assert configured.artifact_s3_secret_key is not None
    assert configured.artifact_s3_secret_key.get_secret_value() == "top-secret-value"
    assert "top-secret-value" not in repr(configured)


@pytest.mark.parametrize(
    "overrides",
    [
        {"artifact_s3_region": None},
        {"artifact_s3_endpoint": "http://user@127.0.0.1:3900"},
        {"artifact_s3_endpoint": "http://127.0.0.1:3900/private"},
        {"artifact_max_bytes": 16 * 1024 * 1024 + 1},
    ],
)
def test_enabled_artifact_configuration_matches_the_bounded_adapter(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "artifact_s3_endpoint": "http://127.0.0.1:3900",
        "artifact_s3_bucket": "polycolab-test",
        "artifact_s3_region": "garage",
        "artifact_s3_access_key": "access",
        "artifact_s3_secret_key": "top-secret-value",
    }
    with pytest.raises(ValidationError):
        Settings.model_validate({**values, **overrides})
