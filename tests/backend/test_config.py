from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import AnyUrl, SecretStr, ValidationError

from polycolab.model_gateway.credentials import (
    AwsKmsKeyWrapper,
    CredentialError,
    wrapper_from_settings,
)
from polycolab.model_gateway.migration import CredentialKeyring
from polycolab.model_gateway.openbao import OpenBaoKeyWrapper
from polycolab.platform.config import (
    ApiReferenceAccess,
    AuthMode,
    Environment,
    KmsProvider,
    RegistrationMode,
    Settings,
    WorkerSettings,
)


def _deployed_oidc_settings(client_id: str | None = None) -> Settings:
    return Settings(
        app_env=Environment.STAGING,
        auth_mode=AuthMode.OIDC,
        database_url="sqlite+pysqlite:///:memory:",
        oidc_issuer=AnyUrl("https://identity.example"),
        oidc_jwks_url=AnyUrl("https://identity.example/jwks"),
        oidc_audience="polycolab-api",
        oidc_client_id=client_id,
        kms_provider=KmsProvider.AWS,
        kms_key_id="test-kms-key",
        admission_scope_hmac_key=SecretStr("test-admission-key"),
        runtime_worker_token=SecretStr("test-runtime-worker-token"),
    )


def test_deployed_oidc_requires_public_browser_client_id() -> None:
    with pytest.raises(ValidationError, match="OIDC_CLIENT_ID is required for OIDC"):
        _deployed_oidc_settings()

    settings = _deployed_oidc_settings("polycolab-web")
    assert settings.oidc_client_id == "polycolab-web"


def test_openbao_requires_explicit_service_credentials_and_paired_legacy_reader() -> None:
    with pytest.raises(ValidationError, match="OPENBAO_URL and OPENBAO_TOKEN"):
        Settings(kms_provider=KmsProvider.OPENBAO)

    with pytest.raises(ValidationError, match="must be configured together"):
        Settings(
            kms_provider=KmsProvider.OPENBAO,
            openbao_url=AnyUrl("https://bao.example"),
            openbao_token=SecretStr("test-token"),
            legacy_aws_kms_key_id="legacy-key",
        )

    settings = Settings(
        kms_provider=KmsProvider.OPENBAO,
        openbao_url=AnyUrl("https://bao.example"),
        openbao_token=SecretStr("test-token"),
        legacy_aws_kms_key_id="legacy-key",
        legacy_aws_kms_key_version="aws-v1",
    )
    assert settings.openbao_token is not None
    assert settings.openbao_token.get_secret_value() == "test-token"


def test_openbao_loopback_http_override_is_local_only() -> None:
    deployed = _deployed_oidc_settings("polycolab-web").model_dump()
    with pytest.raises(ValidationError, match="only permitted locally"):
        Settings(
            **{
                **deployed,
                "kms_provider": KmsProvider.OPENBAO,
                "openbao_url": AnyUrl("http://127.0.0.1:8200"),
                "openbao_token": SecretStr("test-token"),
                "openbao_allow_loopback_http": True,
            }
        )


def test_openbao_settings_select_new_writer_and_exact_legacy_aws_reader() -> None:
    settings = Settings(
        kms_provider=KmsProvider.OPENBAO,
        openbao_url=AnyUrl("https://bao.example"),
        openbao_token=SecretStr("test-token"),
        openbao_backend_id="primary",
        openbao_key_name="gateway",
        openbao_transit_version=3,
        openbao_historical_transit_versions=[1, 2],
        legacy_aws_kms_key_id="legacy-key",
        legacy_aws_kms_key_version="aws-v1",
    )
    selected = wrapper_from_settings(settings)
    assert isinstance(selected, CredentialKeyring)
    assert selected.key_version == "openbao:v1:primary:local:transit:gateway:3"
    assert isinstance(selected.wrapper("aws-v1"), AwsKmsKeyWrapper)
    assert isinstance(
        selected.wrapper("openbao:v1:primary:local:transit:gateway:1"), OpenBaoKeyWrapper
    )
    assert isinstance(
        selected.wrapper("openbao:v1:primary:local:transit:gateway:2"), OpenBaoKeyWrapper
    )
    with pytest.raises(CredentialError, match="credential_key_version_unavailable"):
        selected.wrapper("openbao:v1:primary:local:transit:gateway:4")
    selected.close()


@pytest.mark.parametrize("versions", [[3], [1, 1], [0], [-1], [True]])
def test_openbao_historical_versions_are_bounded_unique_and_exclude_active(
    versions: list[int],
) -> None:
    with pytest.raises(ValidationError, match="historical OpenBao Transit versions"):
        Settings(
            kms_provider=KmsProvider.OPENBAO,
            openbao_url=AnyUrl("https://bao.example"),
            openbao_token=SecretStr("test-token"),
            openbao_transit_version=3,
            openbao_historical_transit_versions=versions,
        )


def test_local_cors_default_matches_vite_development_server() -> None:
    settings = Settings.model_construct()
    assert [str(origin).rstrip("/") for origin in settings.allowed_origins] == [
        "http://localhost:5173"
    ]


@pytest.mark.parametrize("environment", list(Environment))
def test_builtin_auth_is_default_in_every_environment(environment: Environment) -> None:
    values = _deployed_oidc_settings("polycolab-web").model_dump()
    for key in ("auth_mode", "oidc_issuer", "oidc_jwks_url", "oidc_audience", "oidc_client_id"):
        values.pop(key)
    settings = Settings(**{**values, "app_env": environment, "_env_file": None})
    assert settings.auth_mode is AuthMode.LOCAL
    assert settings.oidc_issuer is None


@pytest.mark.parametrize("environment", list(Environment))
def test_removed_disabled_auth_mode_is_rejected(environment: Environment) -> None:
    values = _deployed_oidc_settings("polycolab-web").model_dump()
    with pytest.raises(ValidationError, match="Input should be 'oidc' or 'local'"):
        Settings(**{**values, "app_env": environment, "auth_mode": "disabled"})


def test_builtin_auth_does_not_relax_other_deployment_guards() -> None:
    values = _deployed_oidc_settings("polycolab-web").model_dump()
    with pytest.raises(ValidationError, match="KMS_PROVIDER=local is only permitted locally"):
        Settings(**{**values, "auth_mode": AuthMode.LOCAL, "kms_provider": KmsProvider.LOCAL})


def test_api_reference_access_defaults_and_legacy_compatibility() -> None:
    deployed = _deployed_oidc_settings("polycolab-web").model_dump()

    assert Settings().reference_access is ApiReferenceAccess.PUBLIC
    assert Settings(**{**deployed, "app_env": Environment.STAGING}).reference_access is (
        ApiReferenceAccess.PUBLIC
    )
    assert Settings(**{**deployed, "app_env": Environment.PRODUCTION}).reference_access is (
        ApiReferenceAccess.DISABLED
    )
    assert (
        Settings(
            **{
                **deployed,
                "app_env": Environment.PRODUCTION,
                "api_reference_enabled": True,
                "api_reference_operator_subjects": ["operator"],
            }
        ).reference_access
        is ApiReferenceAccess.OPERATORS
    )
    assert (
        Settings(
            **{
                **deployed,
                "app_env": Environment.PRODUCTION,
                "api_reference_access": ApiReferenceAccess.PUBLIC,
            }
        ).reference_access
        is ApiReferenceAccess.PUBLIC
    )

    with pytest.raises(ValidationError, match="API_REFERENCE_ACCESS=operators"):
        Settings(api_reference_access=ApiReferenceAccess.OPERATORS)


def test_registration_defaults_closed_and_requires_local_origin_and_deployed_rate_limit() -> None:
    assert Settings().registration_mode is RegistrationMode.CLOSED
    with pytest.raises(ValidationError, match="available only with AUTH_MODE=local"):
        Settings(
            auth_mode=AuthMode.OIDC,
            registration_mode=RegistrationMode.OPEN,
            public_app_origin=AnyUrl("https://app.example"),
        )
    with pytest.raises(ValidationError, match="PUBLIC_APP_ORIGIN is required"):
        Settings(registration_mode=RegistrationMode.OPEN)

    values = _deployed_oidc_settings("polycolab-web").model_dump()
    values.update(
        auth_mode=AuthMode.LOCAL,
        oidc_issuer=None,
        oidc_jwks_url=None,
        oidc_audience=None,
        oidc_authorized_party=None,
        oidc_client_id=None,
        registration_mode=RegistrationMode.OPEN,
        public_app_origin=AnyUrl("https://app.example"),
        registration_requests_per_minute=0,
    )
    with pytest.raises(ValidationError, match="rate limiting is required"):
        Settings(**values)


def test_deployed_local_auth_requires_login_rate_limits() -> None:
    values = _deployed_oidc_settings("polycolab-web").model_dump()
    values.update(
        auth_mode=AuthMode.LOCAL,
        oidc_issuer=None,
        oidc_jwks_url=None,
        oidc_audience=None,
        oidc_authorized_party=None,
        oidc_client_id=None,
        login_address_requests_per_minute=0,
    )
    with pytest.raises(ValidationError, match="login rate limiting is required"):
        Settings(**values)


def test_worker_settings_exclude_database_credentials() -> None:
    assert "database_url" not in WorkerSettings.model_fields


def test_deployed_worker_requires_runtime_identity_token() -> None:
    with pytest.raises(
        ValidationError,
        match="RUNTIME_WORKER_TOKEN is required outside local",
    ):
        WorkerSettings(
            app_env=Environment.STAGING,
            runtime_worker_token=None,
        )


def test_runtime_worker_rotation_requires_a_distinct_paired_expiry() -> None:
    deployed = _deployed_oidc_settings("polycolab-web").model_dump()
    with pytest.raises(ValidationError, match="must be configured together"):
        Settings(**{**deployed, "runtime_worker_previous_token": SecretStr("old")})

    with pytest.raises(ValidationError, match="must differ"):
        Settings(
            **{
                **deployed,
                "runtime_worker_token": SecretStr("same"),
                "runtime_worker_previous_token": SecretStr("same"),
                "runtime_worker_previous_token_expires_at": datetime.now(UTC)
                + timedelta(minutes=5),
            }
        )
