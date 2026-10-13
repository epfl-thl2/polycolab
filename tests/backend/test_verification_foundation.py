"""Shared verification persistence/configuration contract checks."""

from datetime import UTC, datetime

import pytest
from pydantic import SecretStr, ValidationError

from polycolab.platform.config import Settings, VerificationControllerSettings


def test_verification_features_are_independent_and_disabled_by_default() -> None:
    settings = Settings()
    assert settings.feature_verification_submission_enabled is False
    assert settings.feature_verification_execution_enabled is False
    assert settings.verification_queue_capacity > 0
    assert settings.verification_user_daily_cpu_seconds > 0
    assert settings.verification_project_daily_memory_byte_seconds > 0
    assert "database_url" not in VerificationControllerSettings.model_fields


def test_verification_enablement_requires_storage_and_controller_authority() -> None:
    with pytest.raises(ValidationError, match="artifact storage must be configured"):
        Settings(feature_verification_submission_enabled=True)
    with pytest.raises(ValidationError, match="VERIFICATION_CONTROLLER_TOKEN"):
        Settings(feature_verification_execution_enabled=True)


def test_controller_credential_rotation_is_explicit_and_distinct() -> None:
    expiry = datetime(2026, 9, 8, tzinfo=UTC)
    with pytest.raises(ValidationError, match="must be configured together"):
        Settings(verification_controller_previous_token=SecretStr("previous"))
    with pytest.raises(ValidationError, match="must differ"):
        Settings(
            verification_controller_token=SecretStr("same"),
            verification_controller_previous_token=SecretStr("same"),
            verification_controller_previous_token_expires_at=expiry,
        )
    controller = VerificationControllerSettings(
        verification_controller_token=SecretStr("controller-secret")
    )
    assert controller.verification_controller_secret == "controller-secret"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("verification_queue_capacity", 0),
        ("verification_user_concurrent_jobs", 0),
        ("verification_max_attempts", 0),
        ("verification_lease_seconds", 0),
        ("verification_deadline_seconds", 0),
        ("verification_event_page_size", 0),
    ],
)
def test_verification_limits_do_not_use_zero_as_unlimited(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({field: value})
