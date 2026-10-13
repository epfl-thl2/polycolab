"""Deployment configuration gate tests; no deployment or network acceptance claimed."""

from pathlib import Path

import pytest
from pydantic import AnyUrl, SecretStr

from polycolab.operations.deployment_preflight import MIGRATIONS_DIR, configuration_failures, main
from polycolab.platform.config import AuthMode, Environment, KmsProvider, RegistrationMode, Settings


def deployment_settings() -> Settings:
    return Settings(
        app_env=Environment.PRODUCTION,
        database_url="postgresql+psycopg://research:synthetic@postgres/research",
        auth_mode=AuthMode.LOCAL,
        registration_mode=RegistrationMode.OPEN,
        public_app_origin=AnyUrl("https://research.example"),
        allowed_origins=[AnyUrl("https://research.example")],
        kms_provider=KmsProvider.AWS,
        kms_key_id="synthetic-test-key",
        runtime_worker_token=SecretStr("s" * 32),
        admission_scope_hmac_key=SecretStr("h" * 32),
        release_sha="abc123",
        public_project_moderator_subjects=["research-operator"],
        feature_agent_execution_enabled=False,
        artifact_s3_endpoint=AnyUrl("http://garage:3900"),
        artifact_s3_bucket="research",
        artifact_s3_region="garage",
        artifact_s3_access_key=SecretStr("synthetic-key"),
        artifact_s3_secret_key=SecretStr("synthetic-secret"),
    )


def test_migration_directory_points_to_the_backend_alembic_tree() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    assert MIGRATIONS_DIR.name == "postgresql"
    assert MIGRATIONS_DIR.parent.name == "migrations"
    assert (MIGRATIONS_DIR / "env.py").is_file()
    config = Config(str(MIGRATIONS_DIR.parents[3] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert Path(scripts.dir) == MIGRATIONS_DIR
    assert scripts.get_current_head() is not None


def test_valid_deployment_configuration() -> None:
    assert configuration_failures(deployment_settings()) == []


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("release_sha", "unknown", "release_identifier"),
        ("release_sha", "CHANGE_ME_COMMIT", "placeholders"),
        ("artifact_s3_secret_key", SecretStr("CHANGE_ME"), "placeholders"),
        ("allowed_origins", [], "same_origin"),
        ("artifact_s3_endpoint", None, "storage_configuration"),
        ("admission_trusted_proxy_cidrs", ["0.0.0.0/0"], "proxy_scope"),
    ],
)
def test_rejects_incompatible_deployment_configuration(
    field: str, value: object, code: str
) -> None:
    settings = deployment_settings().model_copy(update={field: value})
    assert code in configuration_failures(settings)


def test_live_release_gate_requires_a_moderation_operator_after_bootstrap() -> None:
    settings = deployment_settings().model_copy(update={"public_project_moderator_subjects": []})
    assert "moderation_operators" not in configuration_failures(settings)
    assert "moderation_operators" in configuration_failures(
        settings, require_moderation_operator=True
    )


def test_validation_errors_do_not_disclose_inputs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def invalid_settings() -> Settings:
        raise ValueError("synthetic-private-token")

    monkeypatch.setattr("polycolab.operations.deployment_preflight.Settings", invalid_settings)
    assert main([]) == 1
    assert capsys.readouterr().out == "deployment configuration: INVALID_SETTINGS\n"


@pytest.mark.parametrize(
    "capability",
    [
        "feature_agent_execution_enabled",
    ],
)
def test_preflight_does_not_prescribe_a_product_subset(capability: str) -> None:
    for enabled in (False, True):
        settings = deployment_settings().model_copy(update={capability: enabled})
        assert configuration_failures(settings) == []
