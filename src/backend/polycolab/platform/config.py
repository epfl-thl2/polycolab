"""Environment-specific settings for the application service."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import AnyUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Source checkouts share deploy/docker/.env. Installed containers use only
# injected settings; no implicit working-directory dotenv fallback.
_source_root = next(
    (
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "src/backend/pyproject.toml").is_file()
    ),
    None,
)
_env_file = _source_root / "deploy/docker/.env" if _source_root is not None else None


class Environment(StrEnum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class AuthMode(StrEnum):
    OIDC = "oidc"
    LOCAL = "local"


class ApiReferenceAccess(StrEnum):
    DISABLED = "disabled"
    PUBLIC = "public"
    OPERATORS = "operators"


class RegistrationMode(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    INVITATION = "invitation"


class KmsProvider(StrEnum):
    LOCAL = "local"
    AWS = "aws"
    OPENBAO = "openbao"


class Settings(BaseSettings):
    """Settings loaded from environment variables, never from application code."""

    model_config = SettingsConfigDict(env_file=_env_file, env_file_encoding="utf-8", extra="ignore")

    app_env: Environment = Environment.LOCAL
    service_name: str = "polycolab-api"
    service_version: str = "0.0.0"
    # Deployment supplies the immutable release identifier used by redacted
    # operator diagnostics; it is never derived from a client request.
    release_sha: str = Field(default="unknown", min_length=1, max_length=128)
    database_url: str = "postgresql+psycopg://polycolab:polycolab@localhost:5432/polycolab"
    database_pool_size: int = Field(default=5, ge=1, le=1000)
    database_max_overflow: int = Field(default=5, ge=0, le=1000)
    database_pool_timeout_seconds: float = Field(default=30.0, gt=0, le=300, allow_inf_nan=False)
    allowed_origins: list[AnyUrl] = Field(default_factory=lambda: [AnyUrl("http://localhost:5173")])
    log_level: str = "INFO"
    log_json: bool | None = None
    auth_mode: AuthMode = AuthMode.LOCAL
    bootstrap_admin_password: SecretStr | None = Field(default=None, min_length=12, max_length=256)
    local_auth_session_ttl_seconds: int = Field(default=604_800, ge=300, le=2_592_000)
    local_auth_cookie_name: str = Field(default="polycolab_session", min_length=1, max_length=64)
    registration_mode: RegistrationMode = RegistrationMode.CLOSED
    registration_invitation_ttl_seconds: int = Field(default=604_800, ge=300, le=2_592_000)
    registration_requests_per_minute: int = Field(default=5, ge=0, le=1000)
    login_address_requests_per_minute: int = Field(default=20, ge=0, le=1000)
    login_username_requests_per_minute: int = Field(default=10, ge=0, le=1000)
    registration_max_request_bytes: int = Field(default=4096, ge=512, le=65_536)
    public_app_origin: AnyUrl | None = None
    account_recovery_reauthentication_seconds: int = Field(default=300, ge=60, le=900)
    account_recovery_requests_per_hour: int = Field(default=5, ge=1, le=100)
    mail_outbox_lease_seconds: int = Field(default=60, ge=10, le=300)
    mail_outbox_max_attempts: int = Field(default=8, ge=1, le=100)
    mail_outbox_retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    smtp_host: str | None = Field(default=None, min_length=1, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65_535)
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_password: SecretStr | None = Field(default=None, max_length=4096)
    smtp_from_address: str | None = Field(default=None, min_length=3, max_length=320)
    smtp_starttls: bool = True
    social_google_client_id: str | None = Field(default=None, min_length=1, max_length=500)
    social_google_client_secret: SecretStr | None = Field(
        default=None, min_length=1, max_length=4096
    )
    social_github_client_id: str | None = Field(default=None, min_length=1, max_length=500)
    social_github_client_secret: SecretStr | None = Field(
        default=None, min_length=1, max_length=4096
    )
    social_auth_transaction_ttl_seconds: int = Field(default=300, ge=60, le=600)
    social_link_reauthentication_seconds: int = Field(default=300, ge=60, le=900)
    oidc_issuer: AnyUrl | None = None
    oidc_jwks_url: AnyUrl | None = None
    oidc_audience: str | None = None
    oidc_authorized_party: str | None = None
    # Public OAuth client metadata used by the browser's authorization-code
    # flow. This is an identifier, not a client secret.
    oidc_client_id: str | None = Field(default=None, min_length=1, max_length=500)
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    # The production image copies the Vite output here. Source checkouts also
    # discover src/web/dist when no explicit path is configured.
    web_dist_dir: str | None = None
    # The legacy flag remains a compatibility input. New deployments should use
    # API_REFERENCE_ACCESS so public documentation is always an explicit choice
    # in production.
    api_reference_enabled: bool | None = None
    api_reference_access: ApiReferenceAccess | None = None
    api_reference_operator_subjects: list[str] = Field(default_factory=list)
    kms_provider: KmsProvider = KmsProvider.LOCAL
    kms_key_id: str | None = None
    kms_key_version: str = "v1"
    kms_region: str | None = None
    # OpenBao is the self-hosted production writer. A legacy AWS reader may be
    # registered during a bounded migration window; stored envelope versions
    # select readers exactly and are never guessed.
    openbao_url: AnyUrl | None = None
    openbao_token: SecretStr | None = None
    openbao_backend_id: str = "primary"
    openbao_mount: str = "transit"
    openbao_key_name: str = "gateway"
    openbao_transit_version: int = Field(default=1, ge=1, le=2**31 - 1)
    openbao_historical_transit_versions: list[int] = Field(default_factory=list, max_length=32)
    openbao_allow_loopback_http: bool = False
    legacy_aws_kms_key_id: str | None = None
    legacy_aws_kms_key_version: str | None = None
    legacy_aws_kms_region: str | None = None
    # Only valid in local/test. The example value is intentionally absent.
    local_credential_master_key: str | None = None
    gateway_run_token_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    gateway_request_timeout_seconds: float = Field(default=30, gt=0, le=300)
    gateway_max_output_tokens: int = Field(default=8192, ge=1, le=100_000)
    gateway_max_input_bytes: int = Field(default=262_144, ge=1, le=10_000_000)
    gateway_max_response_bytes: int = Field(default=1_000_000, ge=1, le=20_000_000)
    gateway_retry_count: int = Field(default=1, ge=0, le=3)
    gateway_retry_backoff_seconds: float = Field(default=0.1, ge=0, le=10)
    # Operators configure conservative rates at or above the most expensive
    # permitted provider. A request reserves its worst case across all retries.
    gateway_input_microusd_per_million_tokens: int = Field(default=10_000_000, ge=0)
    gateway_output_microusd_per_million_tokens: int = Field(default=30_000_000, ge=0)
    gateway_max_cost_microusd: int = Field(default=1_000_000, ge=1)
    runtime_lease_seconds: int = Field(default=30, ge=5, le=300)
    runtime_max_attempts: int = Field(default=2, ge=1, le=5)
    runtime_max_model_rounds: int = Field(default=4, ge=1, le=16)
    hosted_agent_capacity: int = Field(default=4, ge=0, le=64)
    hosted_agent_user_capacity: int = Field(default=2, ge=1, le=32)
    hosted_agent_workspace_capacity: int = Field(default=2, ge=1, le=32)
    runtime_codex_image: str | None = Field(default=None, pattern=r"^[^\s]+@sha256:[0-9a-f]{64}$")
    runtime_run_timeout_seconds: int = Field(default=300, ge=10, le=3600)
    runtime_sse_poll_seconds: float = Field(default=0.25, gt=0, le=5)
    runtime_sse_heartbeat_seconds: int = Field(default=15, ge=5, le=60)
    runtime_event_batch_size: int = Field(default=100, ge=1, le=1000)
    # Private API address available only to the built-in worker deployment. It is
    # never returned through the application API or accepted from browser input.
    runtime_internal_api_url: str = "http://127.0.0.1:8000"
    runtime_worker_id: str = Field(default="builtin-worker", min_length=1, max_length=200)
    # Deployment-managed bearer credential used only on the private Runtime API.
    # A separate WorkerSettings model lets the worker run without DATABASE_URL.
    runtime_worker_token: SecretStr | None = None
    # An overlap credential permits zero-downtime rotation. It is accepted only
    # until the explicitly configured deadline and should then be removed.
    runtime_worker_previous_token: SecretStr | None = None
    runtime_worker_previous_token_expires_at: datetime | None = None
    runtime_api_max_request_bytes: int = Field(default=400_000, ge=1, le=10_000_000)
    runtime_api_max_response_bytes: int = Field(default=1_000_000, ge=1, le=20_000_000)
    runtime_worker_poll_seconds: float = Field(default=0.25, gt=0, le=5)
    # Human moderation of public workspaces is separate from Library moderation.
    public_workspace_moderator_subjects: list[str] = Field(default_factory=list)
    external_agent_credential_ttl_seconds: int = Field(default=2_592_000, ge=3600, le=31_536_000)
    external_agent_max_requests: int = Field(default=10_000, ge=1, le=1_000_000)
    external_agent_max_mutations: int = Field(default=1_000, ge=1, le=100_000)
    workspace_repository_directory: Path | None = None
    workspace_repository_max_bytes: int = Field(
        default=64 * 1024 * 1024, ge=1024 * 1024, le=1024 * 1024 * 1024
    )
    artifact_local_directory: Path | None = None
    artifact_s3_endpoint: AnyUrl | None = None
    artifact_s3_bucket: str | None = Field(default=None, min_length=1, max_length=255)
    artifact_s3_region: str | None = Field(default=None, min_length=1, max_length=100)
    artifact_s3_access_key: SecretStr | None = None
    artifact_s3_secret_key: SecretStr | None = None
    artifact_max_bytes: int = Field(default=16 * 1024 * 1024, ge=1, le=16 * 1024 * 1024)
    artifact_request_timeout_seconds: float = Field(default=30, gt=0, le=300)
    artifact_staging_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)
    artifact_gc_grace_seconds: int = Field(default=300, ge=0, le=86_400)
    # Verification admission and source execution are separate gates. Both stay
    # disabled until their respective Step 14 and Linux-isolation evidence lands.
    feature_verification_submission_enabled: bool = False
    feature_verification_execution_enabled: bool = False
    verification_internal_api_url: str = "http://127.0.0.1:8000"
    verification_controller_id: str = Field(
        default="verification-controller", min_length=1, max_length=200
    )
    verification_controller_token: SecretStr | None = None
    verification_controller_previous_token: SecretStr | None = None
    verification_controller_previous_token_expires_at: datetime | None = None
    verification_queue_capacity: int = Field(default=1000, ge=1, le=100_000)
    verification_user_concurrent_jobs: int = Field(default=2, ge=1, le=100)
    verification_workspace_concurrent_jobs: int = Field(default=8, ge=1, le=1000)
    verification_user_daily_cpu_seconds: int = Field(default=28_800, ge=1)
    verification_workspace_daily_cpu_seconds: int = Field(default=115_200, ge=1)
    verification_user_daily_memory_byte_seconds: int = Field(
        default=8 * 1024 * 1024 * 1024 * 3600, ge=1
    )
    verification_workspace_daily_memory_byte_seconds: int = Field(
        default=32 * 1024 * 1024 * 1024 * 3600, ge=1
    )
    verification_max_attempts: int = Field(default=2, ge=1, le=5)
    verification_lease_seconds: int = Field(default=30, ge=5, le=300)
    verification_deadline_seconds: int = Field(default=3600, ge=10, le=3600)
    verification_manifest_max_inputs: int = Field(default=128, ge=1, le=128)
    verification_event_page_size: int = Field(default=100, ge=1, le=1000)
    verification_event_payload_bytes: int = Field(default=16_384, ge=1, le=262_144)
    verification_diagnostic_payload_bytes: int = Field(default=65_536, ge=1, le=1_048_576)
    verification_controller_poll_seconds: float = Field(default=0.25, gt=0, le=5)
    verification_api_max_request_bytes: int = Field(default=262_144, ge=1, le=10_000_000)
    verification_api_max_response_bytes: int = Field(default=1_000_000, ge=1, le=20_000_000)
    catalogue_operator_subjects: list[str] = Field(default_factory=list)
    feature_agent_execution_enabled: bool = False
    execution_user_requests_per_minute: int = Field(default=30, ge=0, le=10_000)
    execution_project_requests_per_minute: int = Field(default=120, ge=0, le=10_000)
    execution_user_concurrent_runs: int = Field(default=2, ge=0, le=100)
    execution_project_concurrent_runs: int = Field(default=8, ge=0, le=1000)
    execution_user_daily_tokens: int = Field(default=10_000_000, ge=0)
    execution_project_daily_tokens: int = Field(default=100_000_000, ge=0)
    execution_user_daily_cost_microusd: int = Field(default=200_000_000, ge=0)
    execution_project_daily_cost_microusd: int = Field(default=2_000_000_000, ge=0)
    # One token per input byte is intentionally pessimistic. It makes the
    # pilot ceiling independent of provider tokenizer behavior.
    execution_max_input_tokens_per_round: int = Field(default=262_144, ge=1)
    execution_rate_window_retention_minutes: int = Field(default=120, ge=1, le=10_080)
    # Public reads are grouped by an HMAC-derived client-address identifier.
    # Zero disables a limit deliberately, which is useful for local development.
    public_read_requests_per_minute: int = Field(default=120, ge=0, le=100_000)
    sse_reconnects_per_minute: int = Field(default=30, ge=0, le=10_000)
    admission_scope_hmac_key: SecretStr | None = None
    admission_trusted_proxy_cidrs: list[str] = Field(default_factory=list)
    operator_diagnostics_enabled: bool = False
    operator_diagnostics_subjects: list[str] = Field(default_factory=list)

    @field_validator(
        "database_pool_size",
        "database_max_overflow",
        "database_pool_timeout_seconds",
        mode="before",
    )
    @classmethod
    def reject_boolean_database_pool_values(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("database pool values must be numeric, not boolean")
        return value

    @field_validator("openbao_historical_transit_versions", mode="before")
    @classmethod
    def validate_historical_openbao_versions(cls, value: object) -> object:
        if not isinstance(value, list) or any(type(version) is not int for version in value):
            raise ValueError("historical OpenBao Transit versions must be integer lists")
        return value

    @model_validator(mode="after")
    def validate_deployment_settings(self) -> Settings:
        if self.app_env is Environment.PRODUCTION and self.database_url.endswith(
            "polycolab@localhost:5432/polycolab"
        ):
            raise ValueError("DATABASE_URL must be explicitly configured in production")
        if (
            self.auth_mode is not AuthMode.LOCAL
            and self.registration_mode is not RegistrationMode.CLOSED
        ):
            raise ValueError("registration is available only with AUTH_MODE=local")
        if (
            self.auth_mode is AuthMode.LOCAL
            and self.app_env is not Environment.LOCAL
            and (
                self.login_address_requests_per_minute == 0
                or self.login_username_requests_per_minute == 0
            )
        ):
            raise ValueError("login rate limiting is required outside local")
        if self.registration_mode is not RegistrationMode.CLOSED:
            if self.public_app_origin is None:
                raise ValueError("PUBLIC_APP_ORIGIN is required when registration is enabled")
            if self.app_env is not Environment.LOCAL and self.registration_requests_per_minute == 0:
                raise ValueError("registration rate limiting is required outside local")
        social_pairs = (
            (self.social_google_client_id, self.social_google_client_secret),
            (self.social_github_client_id, self.social_github_client_secret),
        )
        if any(
            (client_id is None) != (client_secret is None)
            for client_id, client_secret in social_pairs
        ):
            raise ValueError("each social provider requires both client ID and client secret")
        if any(client_id is not None for client_id, _ in social_pairs) or (
            self.registration_mode is not RegistrationMode.CLOSED
        ):
            origin = self.public_app_origin
            if origin is None:
                raise ValueError("PUBLIC_APP_ORIGIN is required when social sign-in is configured")
            authority = str(origin).split("//", 1)[-1].split("/", 1)[0]
            loopback = origin.host in {"localhost", "127.0.0.1", "::1"}
            if (
                "@" in authority
                or origin.query is not None
                or origin.fragment is not None
                or origin.path not in {None, "", "/"}
                or not (
                    origin.scheme == "https"
                    or self.app_env is Environment.LOCAL
                    and origin.scheme == "http"
                    and loopback
                )
            ):
                raise ValueError(
                    "PUBLIC_APP_ORIGIN for browser auth must be an HTTPS origin without "
                    "credentials or path; "
                    "local loopback HTTP is allowed only in local development"
                )
        if self.app_env is not Environment.LOCAL and self.kms_provider is KmsProvider.LOCAL:
            raise ValueError("KMS_PROVIDER=local is only permitted locally")
        if self.kms_provider is KmsProvider.AWS and not self.kms_key_id:
            raise ValueError("KMS_KEY_ID is required when KMS_PROVIDER=aws")
        if self.kms_provider is KmsProvider.OPENBAO and (
            self.openbao_url is None or self.openbao_token is None
        ):
            raise ValueError("OPENBAO_URL and OPENBAO_TOKEN are required when KMS_PROVIDER=openbao")
        historical_versions = self.openbao_historical_transit_versions
        if historical_versions and self.kms_provider is not KmsProvider.OPENBAO:
            raise ValueError("OPENBAO_HISTORICAL_TRANSIT_VERSIONS requires KMS_PROVIDER=openbao")
        if (
            len(set(historical_versions)) != len(historical_versions)
            or any(type(version) is not int or version < 1 for version in historical_versions)
            or self.openbao_transit_version in historical_versions
        ):
            raise ValueError(
                "historical OpenBao Transit versions must be unique positive integers "
                "excluding the active version"
            )
        if self.openbao_allow_loopback_http and self.app_env is not Environment.LOCAL:
            raise ValueError("OPENBAO_ALLOW_LOOPBACK_HTTP is only permitted locally")
        if (self.legacy_aws_kms_key_id is None) != (self.legacy_aws_kms_key_version is None):
            raise ValueError(
                "LEGACY_AWS_KMS_KEY_ID and LEGACY_AWS_KMS_KEY_VERSION must be configured together"
            )
        if self.app_env is not Environment.LOCAL and (
            self.gateway_input_microusd_per_million_tokens == 0
            or self.gateway_output_microusd_per_million_tokens == 0
        ):
            raise ValueError("gateway price ceilings must be configured outside local")
        if self.auth_mode is AuthMode.OIDC and (
            self.oidc_issuer is None or self.oidc_jwks_url is None
        ):
            # Local tests inject an IdentityVerifier directly; normal deployments
            # must declare an OIDC trust boundary rather than silently disabling it.
            if self.app_env is not Environment.LOCAL:
                raise ValueError("OIDC_ISSUER and OIDC_JWKS_URL are required for OIDC")
        if self.app_env is not Environment.LOCAL and self.auth_mode is AuthMode.OIDC:
            if self.oidc_audience is None:
                raise ValueError("OIDC_AUDIENCE is required for OIDC")
            if self.oidc_client_id is None:
                raise ValueError("OIDC_CLIENT_ID is required for OIDC")
            for url in (self.oidc_issuer, self.oidc_jwks_url):
                authority = str(url).split("//", 1)[-1].split("/", 1)[0] if url else ""
                if url is None or url.scheme != "https" or "@" in authority:
                    raise ValueError("OIDC issuer and JWKS URL must be HTTPS without userinfo")
        if (
            self.reference_access is ApiReferenceAccess.OPERATORS
            and not self.api_reference_operator_subjects
        ):
            raise ValueError(
                "API_REFERENCE_OPERATOR_SUBJECTS is required when API_REFERENCE_ACCESS=operators"
            )
        if self.operator_diagnostics_enabled and not self.operator_diagnostics_subjects:
            raise ValueError(
                "OPERATOR_DIAGNOSTICS_SUBJECTS is required when diagnostics are enabled"
            )
        if (
            self.workspace_repository_directory is not None
            and not self.workspace_repository_directory.is_absolute()
        ):
            raise ValueError("WORKSPACE_REPOSITORY_DIRECTORY must be absolute")
        if self.artifact_local_directory is not None:
            if self.app_env is not Environment.LOCAL or not self.database_url.startswith("sqlite"):
                raise ValueError("filesystem artifacts require local SQLite mode")
            if not self.artifact_local_directory.is_absolute():
                raise ValueError("ARTIFACT_LOCAL_DIRECTORY must be absolute")
        storage_fields = (
            self.artifact_s3_endpoint,
            self.artifact_s3_bucket,
            self.artifact_s3_region,
            self.artifact_s3_access_key,
            self.artifact_s3_secret_key,
        )
        if any(value is not None for value in storage_fields) and not all(
            value is not None for value in storage_fields
        ):
            raise ValueError(
                "artifact endpoint, bucket, region, access key and secret key "
                "must be configured together"
            )
        if (self.smtp_host is None) != (self.smtp_from_address is None):
            raise ValueError("SMTP_HOST and SMTP_FROM_ADDRESS must be configured together")
        if (self.smtp_username is None) != (self.smtp_password is None):
            raise ValueError("SMTP_USERNAME and SMTP_PASSWORD must be configured together")
        if self.artifact_s3_endpoint is not None:
            endpoint = self.artifact_s3_endpoint
            authority = str(endpoint).split("//", 1)[-1].split("/", 1)[0]
            if (
                endpoint.scheme not in {"http", "https"}
                or "@" in authority
                or endpoint.query is not None
                or endpoint.fragment is not None
                or endpoint.path not in {None, "", "/"}
            ):
                raise ValueError(
                    "ARTIFACT_S3_ENDPOINT must be HTTP(S) without userinfo, path, query or fragment"
                )
        if self.feature_verification_submission_enabled and not self.artifact_storage_configured:
            raise ValueError("artifact storage must be configured before verification submission")
        if (
            self.feature_verification_execution_enabled
            and self.verification_controller_token is None
        ):
            raise ValueError("VERIFICATION_CONTROLLER_TOKEN is required when execution is enabled")
        controller_previous = self.verification_controller_previous_token
        controller_previous_expiry = self.verification_controller_previous_token_expires_at
        if (controller_previous is None) != (controller_previous_expiry is None):
            raise ValueError(
                "VERIFICATION_CONTROLLER_PREVIOUS_TOKEN and its expiry must be configured together"
            )
        if (
            controller_previous is not None
            and self.verification_controller_token is not None
            and controller_previous.get_secret_value()
            == self.verification_controller_token.get_secret_value()
        ):
            raise ValueError("current and previous verification controller tokens must differ")
        if self.execution_max_input_tokens_per_round < self.gateway_max_input_bytes:
            raise ValueError("execution input reservation must cover GATEWAY_MAX_INPUT_BYTES")
        if self.app_env is not Environment.LOCAL and self.admission_scope_hmac_key is None:
            raise ValueError("ADMISSION_SCOPE_HMAC_KEY is required outside local")
        if self.app_env is not Environment.LOCAL and self.runtime_worker_token is None:
            raise ValueError("RUNTIME_WORKER_TOKEN is required outside local")
        previous = self.runtime_worker_previous_token
        previous_expiry = self.runtime_worker_previous_token_expires_at
        if (previous is None) != (previous_expiry is None):
            raise ValueError(
                "RUNTIME_WORKER_PREVIOUS_TOKEN and its expiry must be configured together"
            )
        if (
            previous is not None
            and self.runtime_worker_token is not None
            and previous.get_secret_value() == self.runtime_worker_token.get_secret_value()
        ):
            raise ValueError("current and previous runtime worker tokens must differ")
        return self

    @field_validator("admission_trusted_proxy_cidrs")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, values: list[str]) -> list[str]:
        # Keep validation here without retaining parsed network objects in the
        # settings model, which remains environment-serializable.
        from ipaddress import ip_network

        for value in values:
            ip_network(value, strict=False)
        return values

    @property
    def use_json_logs(self) -> bool:
        return self.log_json if self.log_json is not None else self.app_env is not Environment.LOCAL

    @property
    def artifact_storage_configured(self) -> bool:
        return self.artifact_local_directory is not None or all(
            value is not None
            for value in (
                self.artifact_s3_endpoint,
                self.artifact_s3_bucket,
                self.artifact_s3_region,
                self.artifact_s3_access_key,
                self.artifact_s3_secret_key,
            )
        )

    @property
    def reference_enabled(self) -> bool:
        return self.reference_access is not ApiReferenceAccess.DISABLED

    @property
    def reference_access(self) -> ApiReferenceAccess:
        if self.api_reference_access is not None:
            return self.api_reference_access
        if self.api_reference_enabled is False:
            return ApiReferenceAccess.DISABLED
        if self.app_env is Environment.PRODUCTION:
            return (
                ApiReferenceAccess.OPERATORS
                if self.api_reference_enabled is True
                else ApiReferenceAccess.DISABLED
            )
        return ApiReferenceAccess.PUBLIC

    @property
    def social_provider_names(self) -> tuple[str, ...]:
        if self.auth_mode is not AuthMode.LOCAL:
            return ()
        names: list[str] = []
        if self.social_google_client_id is not None:
            names.append("google")
        if self.social_github_client_id is not None:
            names.append("github")
        return tuple(names)

    @property
    def public_origin(self) -> str:
        if self.public_app_origin is None:
            raise ValueError("PUBLIC_APP_ORIGIN is not configured")
        return str(self.public_app_origin).rstrip("/")

    @property
    def admission_hmac_key(self) -> str:
        """A local-only fallback prevents accidental address disclosure in tests."""

        if self.admission_scope_hmac_key is not None:
            return self.admission_scope_hmac_key.get_secret_value()
        return "polycolab-local-admission-scope-key"

    @property
    def runtime_worker_secret(self) -> str:
        """Local fallback is limited to the explicitly local deployment profile."""

        if self.runtime_worker_token is not None:
            return self.runtime_worker_token.get_secret_value()
        return "polycolab-local-runtime-worker-token"

    @property
    def verification_controller_secret(self) -> str:
        if self.verification_controller_token is not None:
            return self.verification_controller_token.get_secret_value()
        return "polycolab-local-verification-controller-token"


class WorkerSettings(BaseSettings):
    """Worker-only configuration; deliberately has no database setting."""

    model_config = SettingsConfigDict(env_file=_env_file, env_file_encoding="utf-8", extra="ignore")

    app_env: Environment = Environment.LOCAL
    runtime_internal_api_url: str = "http://127.0.0.1:8000"
    runtime_worker_id: str = Field(default="builtin-worker", min_length=1, max_length=200)
    runtime_worker_token: SecretStr | None = None
    runtime_worker_poll_seconds: float = Field(default=0.25, gt=0, le=5)
    gateway_request_timeout_seconds: float = Field(default=30, gt=0, le=300)
    gateway_max_response_bytes: int = Field(default=1_000_000, ge=1, le=20_000_000)
    runtime_api_max_request_bytes: int = Field(default=400_000, ge=1, le=10_000_000)
    runtime_api_max_response_bytes: int = Field(default=1_000_000, ge=1, le=20_000_000)

    @model_validator(mode="after")
    def validate_worker_settings(self) -> WorkerSettings:
        if self.app_env is not Environment.LOCAL and self.runtime_worker_token is None:
            raise ValueError("RUNTIME_WORKER_TOKEN is required outside local")
        return self

    @property
    def runtime_worker_secret(self) -> str:
        if self.runtime_worker_token is not None:
            return self.runtime_worker_token.get_secret_value()
        return "polycolab-local-runtime-worker-token"


class VerificationControllerSettings(BaseSettings):
    """Controller-only configuration; deliberately has no database setting."""

    model_config = SettingsConfigDict(env_file=_env_file, env_file_encoding="utf-8", extra="ignore")

    app_env: Environment = Environment.LOCAL
    verification_internal_api_url: str = "http://127.0.0.1:8000"
    verification_controller_id: str = Field(
        default="verification-controller", min_length=1, max_length=200
    )
    verification_controller_token: SecretStr | None = None
    verification_controller_poll_seconds: float = Field(default=0.25, gt=0, le=5)
    verification_api_max_request_bytes: int = Field(default=262_144, ge=1, le=10_000_000)
    verification_api_max_response_bytes: int = Field(default=1_000_000, ge=1, le=20_000_000)

    @model_validator(mode="after")
    def validate_controller_settings(self) -> VerificationControllerSettings:
        if self.app_env is not Environment.LOCAL and self.verification_controller_token is None:
            raise ValueError("VERIFICATION_CONTROLLER_TOKEN is required outside local")
        return self

    @property
    def verification_controller_secret(self) -> str:
        if self.verification_controller_token is not None:
            return self.verification_controller_token.get_secret_value()
        return "polycolab-local-verification-controller-token"


@lru_cache
def get_settings() -> Settings:
    return Settings()
