"""Operational FastAPI application foundation."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from ipaddress import ip_address, ip_network
from pathlib import Path
from uuid import UUID, uuid4

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from polycolab.access.authorization import AuthorizationDenied, WorkspaceNotFound
from polycolab.accounts.authentication import (
    AuthenticationRequired,
    IdentityVerifier,
    current_principal,
    verifier_from_settings,
)
from polycolab.accounts.builtin import (
    AccountAlreadyExists,
    RegistrationClosed,
    RegistrationInvitationInvalid,
    RegistrationInvitationNotFound,
    RegistrationRequestInvalid,
    RegistrationSetupRequired,
)
from polycolab.accounts.delivery import (
    InvitationDelivery,
    InvitationDeliveryUnavailable,
    LocalInvitationOutbox,
    UnconfiguredInvitationDelivery,
)
from polycolab.accounts.ingress import CoreBodyLimitMiddleware, RegistrationBodyLimitMiddleware
from polycolab.accounts.recovery import RecoveryConflict, RecoveryInvalid, RecoveryRateLimited
from polycolab.accounts.social import configured_social_providers
from polycolab.agents.external import (
    ExternalAgentConflict,
    ExternalAgentInvalid,
    ExternalAgentLimit,
    ExternalAgentUploadInterrupted,
)
from polycolab.agents.proposals import ProposalStale
from polycolab.app.reference import arrange_reference
from polycolab.db.session import database_is_ready, make_engine, make_session_factory
from polycolab.db.transaction import make_transaction_factory
from polycolab.entities.repositories import RepositoryError
from polycolab.entities.time import utc_now
from polycolab.execution.limits import (
    ExecutionLimitExceeded,
    enforce_login_address_limit,
    enforce_public_read_limit,
    enforce_registration_limit,
)
from polycolab.model_gateway.credentials import CredentialError, wrapper_from_settings
from polycolab.model_gateway.service import GatewayLimits
from polycolab.model_gateway.transport import ProviderTransport, TransportTimeouts
from polycolab.operations.pool_telemetry import PoolMeter
from polycolab.operations.scrape import CommunityScrape
from polycolab.operations.telemetry import PoolRole
from polycolab.platform.config import (
    ApiReferenceAccess,
    AuthMode,
    Environment,
    RegistrationMode,
    Settings,
    get_settings,
)
from polycolab.platform.logging import configure_logging
from polycolab.platform.observability import metrics, render_durable_prometheus
from polycolab.research.contributions import ContributionConflict
from polycolab.research.objects import ResearchNotFound, StaleRevision
from polycolab.workspaces.service import DomainConflict, InvitationInvalid, MembershipTargetInvalid

logger = structlog.get_logger(__name__)

EXPOSED_HTTP_ERROR_CODES = frozenset(
    {
        "artifact_digest_mismatch",
        "artifact_invalid_declaration",
        "artifact_length_mismatch",
        "artifact_size_limit",
        "artifact_storage_unavailable",
        "artifact_upload_timeout",
        "invalid_agent_credential",
        "invalid_cursor",
        "agent_write_headers_required",
        "public_workspaces_disabled",
        "unsupported_agent_object_kind",
    }
)


ERROR_ENVELOPE_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["error"],
    "properties": {
        "error": {
            "type": "object",
            "required": ["code", "request_id"],
            "properties": {
                "code": {"type": "string"},
                "request_id": {"type": "string", "format": "uuid"},
                "details": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["path", "code"],
                        "properties": {
                            "path": {
                                "type": "array",
                                "items": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                            },
                            "code": {"type": "string"},
                        },
                    },
                },
            },
        }
    },
}


API_INTRODUCTION = """Read public research and contribute through shared `/api/v1` resources.
Browser sessions, human OIDC tokens and external-agent keys use the same core paths.
See [Agent runs and contributions](/docs/developers/agent-runs/) and the
[Polycolab skill](/SKILL.md).

## Start here

- **Discover research:** `GET /api/v1/workspaces?scope=public` lists public workspaces
  without an account. Use `/api/v1/search` to find research.
- **Connect an agent:** Create a named key in
  [Settings → API keys](/settings/api-keys), copy its secret once, and send
  `Authorization: Bearer <key>`. Call `GET /api/v1/me` for identity and budgets.
- **Read member research:** Use `scope=member` for workspace listings and search.
  Keys follow their owner's current and future memberships, including private
  workspaces. Personal notes and conversations are excluded.
- **Contribute:** `POST /api/v1/objects` selects a workspace or exact Library
  statement object version as its destination. No external run is required. Agent keys
  need explicit Library opt-in for public contributions.


## Authentication and authority

Public reads accept anonymous requests. Human authentication uses a same-origin
session cookie or an OIDC bearer token. Agent authentication uses an account-wide
`pca_` bearer key. Explicit invalid Authorization never falls back to a cookie or
anonymous access. Shared reads return the public or member projection allowed by
current access.

Key creation, listing and revocation under `/api/v1/account/agent-keys` are
human-only and restricted to the key owner. Workspace administration, catalogue
admission and private publication remain human-only. Agent keys cannot perform
these operations even when their owner can.

## Agent writes and retries

Send a stable `Idempotency-Key` with object, object-version, comment, relation and
attachment writes. Humans and agents receive `{contribution_id, outputs, replayed}`.
Keep the same key and body when retrying a lost response; authorization is checked
again and committed retries do not consume another mutation. Agent identity
persists across key rotation. Each key retains separate finite budgets.

Read exact sources with `/api/v1/versions/{object_version_id}` and inspect contributions
with `/api/v1/contributions/{contribution_id}`. Activity and contributor profiles
show recorded history subject to current visibility. Public profile counts exclude
private workspaces. External run creation and closure are retired; historical
run records remain readable. Hosted execution is a separate optional service.

Append immutable snapshots through `POST /api/v1/objects/{object_id}/versions`
with `expected_current_object_version_id` and a complete `snapshot`, including
structural relationships. Pins never advance automatically. Read full accessible
history through `GET /api/v1/objects/{object_id}/versions`.

## Pagination and limits

Core collections return `{items, next_cursor}`. Pass `next_cursor` as `cursor`
with the same identity, scope and filters. Default `limit` is 25, maximum 100.
Object-version history is newest first. Deferred array-list APIs document their own
`X-Next-Cursor` response header.

Expired or revoked keys return 401. Finite request/mutation budget exhaustion
returns 429 without a refill delay; inspect remaining budgets with `/api/v1/me`,
which does not consume the key's request budget but remains rate protected.
Core JSON bodies are limited to 1 MiB; artifacts have a separate limit of at most
16 MiB. Errors include a code, request ID and safe validation details.

## Availability and migration

The old agent-prefixed and duplicated public-project core routes are removed.
Use `/workspaces` and shared research resources. Deferred catalogue, publication,
assessment and hosted-agent contracts retain their separate paths and permissions.
Availability of optional APIs depends on deployment settings.

The account-key migration revokes old workspace keys and closes their open runs
while preserving history. Create new keys in Settings after upgrading the migration,
API, WebUI and clients together. Old secrets do not gain broader authority.
"""


def _error_response_reference(description: str) -> dict[str, object]:
    return {
        "description": description,
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}},
    }


def scalar_reference_configuration() -> dict[str, object]:
    """Return the constrained Scalar configuration shared by both renderers."""

    return {
        "spec": {"url": "/api/openapi.json"},
        "proxyUrl": "",
        "telemetry": False,
        "isEditable": False,
        "persistAuth": False,
        "showDeveloperTools": "never",
        # This build-less compatibility fallback cannot import the workspace CSS
        # package, so keep its light-mode mapping aligned with the canonical tokens.
        "customCss": """
.light-mode {
  --scalar-background-1: #ffffff;
  --scalar-background-2: #fafafa;
  --scalar-background-3: #f4f4f5;
  --scalar-background-accent: color-mix(in srgb, #007480 10%, #ffffff);
  --scalar-color-1: #18181b;
  --scalar-color-2: #71717a;
  --scalar-color-3: #413d3a;
  --scalar-color-accent: #007480;
  --scalar-border-color: #e4e4e7;
  --scalar-link-color: #007480;
  --scalar-link-color-hover: color-mix(in srgb, #007480 82%, #413d3a);
  --scalar-sidebar-color-active: #007480;
  --scalar-sidebar-item-active-background: color-mix(in srgb, #007480 10%, #ffffff);
  --scalar-button-1: #007480;
  --scalar-button-1-hover: color-mix(in srgb, #007480 82%, #413d3a);
  --scalar-button-1-color: #ffffff;
  --scalar-color-danger: #b91c1c;
}
a[href="https://www.scalar.com"] { display: none; }
""".strip(),
        "defaultOpenFirstTag": False,
        "hideClientButton": True,
        "hideDarkModeToggle": True,
        "forceDarkModeState": "light",
        "hideTestRequestButton": True,
        "agent": {"disabled": True},
        "mcp": {"disabled": True},
        "pluginUrls": [],
    }


def scalar_reference_html() -> str:
    """A deliberately constrained Scalar configuration, served by Polycolab."""

    configuration = json.dumps(scalar_reference_configuration(), separators=(",", ":"))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Polycolab API reference</title>
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
</head>
<body><script id="api-reference" data-configuration='{configuration}'></script>
<script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference@1.62.6/dist/browser/standalone.js"
integrity="sha384-N7JUv0+P4dgRu102bnNFxOXOXp2ROTMToXk71fUs0MNI1wZpfxZYHVAJTnVMS19o"
crossorigin="anonymous"></script></body></html>"""


def error_response(status_code: int, code: str, request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "request_id": request.state.request_id}},
    )


def _request_id(value: str | None) -> str:
    if value is not None:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return str(uuid4())


def _public_client_address(request: Request, settings: Settings) -> str:
    """Use forwarded addresses only from an explicitly trusted direct proxy."""

    peer = request.client.host if request.client is not None else "unknown"
    try:
        peer_address = ip_address(peer)
    except ValueError:
        return peer
    trusted_networks = [
        ip_network(value, strict=False) for value in settings.admission_trusted_proxy_cidrs
    ]
    if not any(peer_address in network for network in trusted_networks):
        return peer
    forwarded = request.headers.get("X-Forwarded-For")
    if not forwarded:
        return peer
    candidate = forwarded.split(",", maxsplit=1)[0].strip()
    try:
        return str(ip_address(candidate))
    except ValueError:
        return peer


def _enforce_public_read_admission(request: Request, settings: Settings) -> None:
    if (
        request.method != "GET"
        or not any(
            route.path_regex.fullmatch(request.url.path) is not None
            for route in request.app.state.public_read_routes
        )
        or settings.public_read_requests_per_minute <= 0
    ):
        return
    db = request.app.state.session_factory()
    try:
        enforce_public_read_limit(
            db,
            client_address=_public_client_address(request, settings),
            hmac_key=settings.admission_hmac_key,
            limit=settings.public_read_requests_per_minute,
            now=utc_now(),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _enforce_registration_admission(request: Request, settings: Settings) -> None:
    if (
        settings.auth_mode is not AuthMode.LOCAL
        or settings.registration_mode is RegistrationMode.CLOSED
        or settings.registration_requests_per_minute <= 0
    ):
        return
    db = request.app.state.session_factory()
    try:
        enforce_registration_limit(
            db,
            client_address=_public_client_address(request, settings),
            hmac_key=settings.admission_hmac_key,
            limit=settings.registration_requests_per_minute,
            now=utc_now(),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _enforce_login_admission(request: Request, settings: Settings) -> None:
    if settings.auth_mode is not AuthMode.LOCAL or settings.login_address_requests_per_minute <= 0:
        return
    db = request.app.state.session_factory()
    try:
        enforce_login_address_limit(
            db,
            client_address=_public_client_address(request, settings),
            hmac_key=settings.admission_hmac_key,
            limit=settings.login_address_requests_per_minute,
            now=utc_now(),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _web_dist_dir(settings: Settings) -> Path | None:
    if settings.web_dist_dir is not None:
        configured = Path(settings.web_dist_dir).expanduser().resolve()
        return configured if (configured / "index.html").is_file() else None
    source_root = Path(__file__).resolve().parents[3]
    candidates = [
        Path(__file__).resolve().parents[2] / "web-dist",
        source_root / "web" / "dist",
    ]
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "index.html").is_file():
            return resolved
    return None


def _reserved_browser_path(path: str) -> bool:
    first_segment = path.partition("/")[0]
    return first_segment in {"api", "auth", "health", "internal", "public"}


def create_app(
    settings: Settings | None = None,
    identity_verifier: IdentityVerifier | None = None,
    invitation_delivery: InvitationDelivery | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    pool_meter = PoolMeter(settings, PoolRole.API)
    engine = make_engine(settings, pool_class=pool_meter.pool_class)
    app = FastAPI(
        title="Polycolab application service",
        version=settings.service_version,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.pool_meter = pool_meter
    app.state.session_factory = make_session_factory(engine)
    app.state.transaction_factory = make_transaction_factory(app.state.session_factory)
    app.state.community_scrape = CommunityScrape(app.state.session_factory)
    app.state.identity_verifier = identity_verifier or verifier_from_settings(
        settings, app.state.session_factory
    )
    app.state.social_providers = configured_social_providers(settings)
    app.state.credential_wrapper = wrapper_from_settings(settings)
    app.state.provider_transport = ProviderTransport(
        timeouts=TransportTimeouts(
            connect=min(5.0, settings.gateway_request_timeout_seconds),
            read=settings.gateway_request_timeout_seconds,
            write=min(10.0, settings.gateway_request_timeout_seconds),
            pool=min(5.0, settings.gateway_request_timeout_seconds),
        ),
        retry_count=settings.gateway_retry_count,
        retry_backoff_seconds=settings.gateway_retry_backoff_seconds,
        max_request_bytes=settings.gateway_max_input_bytes,
        max_response_bytes=settings.gateway_max_response_bytes,
    )
    app.state.gateway_limits = GatewayLimits(
        run_token_ttl_seconds=settings.gateway_run_token_ttl_seconds,
        max_input_bytes=settings.gateway_max_input_bytes,
        max_output_tokens=settings.gateway_max_output_tokens,
        max_cost_microusd=settings.gateway_max_cost_microusd,
        input_microusd_per_million_tokens=(settings.gateway_input_microusd_per_million_tokens),
        output_microusd_per_million_tokens=(settings.gateway_output_microusd_per_million_tokens),
        max_attempts=settings.gateway_retry_count + 1,
        max_response_bytes=settings.gateway_max_response_bytes,
    )
    app.state.invitation_delivery = invitation_delivery or (
        LocalInvitationOutbox()
        if settings.app_env is Environment.LOCAL
        else UnconfiguredInvitationDelivery()
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin).rstrip("/") for origin in settings.allowed_origins],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Request-ID",
        ],
        expose_headers=["X-Next-Cursor"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        start = time.perf_counter()
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id, method=request.method, path=request.url.path
        )
        response: Response
        try:
            if request.method == "POST" and request.url.path == "/auth/register":
                content_length = request.headers.get("content-length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except ValueError:
                        response = error_response(400, "invalid_content_length", request)
                    else:
                        if declared_length < 0:
                            response = error_response(400, "invalid_content_length", request)
                        elif declared_length > settings.registration_max_request_bytes:
                            response = error_response(
                                413, "registration_request_too_large", request
                            )
                        else:
                            body = await request.body()
                            if len(body) > settings.registration_max_request_bytes:
                                response = error_response(
                                    413, "registration_request_too_large", request
                                )
                            else:
                                _enforce_registration_admission(request, settings)
                                response = await call_next(request)
                else:
                    body = await request.body()
                    if len(body) > settings.registration_max_request_bytes:
                        response = error_response(413, "registration_request_too_large", request)
                    else:
                        _enforce_registration_admission(request, settings)
                        response = await call_next(request)
            elif request.method == "POST" and request.url.path == "/auth/login":
                _enforce_login_admission(request, settings)
                response = await call_next(request)
            elif request.url.path.startswith("/internal/v1/runtime"):
                content_length = request.headers.get("content-length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except ValueError:
                        response = error_response(400, "invalid_content_length", request)
                    else:
                        if declared_length < 0:
                            response = error_response(400, "invalid_content_length", request)
                        elif declared_length > settings.runtime_api_max_request_bytes:
                            response = error_response(413, "runtime_request_too_large", request)
                        else:
                            body = await request.body()
                            response = (
                                error_response(413, "runtime_request_too_large", request)
                                if len(body) > settings.runtime_api_max_request_bytes
                                else await call_next(request)
                            )
                else:
                    body = await request.body()
                    response = (
                        error_response(413, "runtime_request_too_large", request)
                        if len(body) > settings.runtime_api_max_request_bytes
                        else await call_next(request)
                    )
            else:
                _enforce_public_read_admission(request, settings)
                response = await call_next(request)
        except ExecutionLimitExceeded as exception:
            metrics.increment("polycolab_quota_rejections_total", quota_kind=exception.code)
            response = error_response(429, exception.code, request)
            response.headers["Retry-After"] = str(exception.retry_after_seconds)
        except Exception:
            logger.exception("unhandled_request_error")
            response = error_response(500, "internal_error", request)
        if request.url.path.startswith("/auth/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Request-ID"] = request_id
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        duration_seconds = time.perf_counter() - start
        metrics.increment(
            "polycolab_http_requests_total",
            service=settings.service_name,
            route=route_path,
            status_class=f"{response.status_code // 100}xx",
        )
        metrics.observe(
            "polycolab_http_request_duration_seconds",
            duration_seconds,
            service=settings.service_name,
            route=route_path,
        )
        logger.info(
            "request_completed",
            status_code=response.status_code,
            duration_ms=round(duration_seconds * 1000, 2),
        )
        if request.url.path.startswith("/api/v1/"):
            response.headers["Cache-Control"] = "private, no-store"
        structlog.contextvars.clear_contextvars()
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exception: StarletteHTTPException
    ) -> JSONResponse:
        detail = exception.detail
        if isinstance(detail, str) and detail in EXPOSED_HTTP_ERROR_CODES:
            code = detail
        elif exception.status_code == 404:
            code = "not_found"
        else:
            code = "http_error"
        response = error_response(exception.status_code, code, request)
        if exception.headers:
            response.headers.update(exception.headers)
        if code == "invalid_agent_credential":
            response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exception: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "request_id": request.state.request_id,
                    "details": [
                        {
                            "path": list(item["loc"][:-1]) + ["*"]
                            if item["type"] == "extra_forbidden"
                            else list(item["loc"]),
                            "code": item["type"],
                        }
                        for item in exception.errors()
                    ],
                }
            },
        )

    @app.exception_handler(AuthenticationRequired)
    async def authentication_required_handler(
        request: Request, _: AuthenticationRequired
    ) -> JSONResponse:
        metrics.increment(
            "polycolab_authorization_denials_total", boundary="http", reason="unauthenticated"
        )
        response = error_response(401, "unauthenticated", request)
        response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @app.exception_handler(RepositoryError)
    async def repository_exception_handler(
        request: Request, exception: RepositoryError
    ) -> JSONResponse:
        return error_response(exception.status, exception.code, request)

    @app.exception_handler(WorkspaceNotFound)
    async def project_not_found_handler(request: Request, _: WorkspaceNotFound) -> JSONResponse:
        return error_response(404, "not_found", request)

    @app.exception_handler(ResearchNotFound)
    async def research_not_found_handler(request: Request, _: ResearchNotFound) -> JSONResponse:
        return error_response(404, "not_found", request)

    @app.exception_handler(AuthorizationDenied)
    async def authorization_denied_handler(
        request: Request, _: AuthorizationDenied
    ) -> JSONResponse:
        metrics.increment(
            "polycolab_authorization_denials_total", boundary="http", reason="forbidden"
        )
        return error_response(403, "forbidden", request)

    @app.exception_handler(ExternalAgentInvalid)
    async def external_agent_invalid_handler(
        request: Request, _: ExternalAgentInvalid
    ) -> JSONResponse:
        response = error_response(401, "invalid_agent_credential", request)
        response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @app.exception_handler(ExternalAgentConflict)
    async def external_agent_conflict_handler(
        request: Request, _: ExternalAgentConflict
    ) -> JSONResponse:
        return error_response(409, "external_agent_conflict", request)

    @app.exception_handler(ExternalAgentLimit)
    async def external_agent_limit_handler(
        request: Request, exception: ExternalAgentLimit
    ) -> JSONResponse:
        return error_response(429, str(exception) or "external_agent_limit", request)

    @app.exception_handler(ExternalAgentUploadInterrupted)
    async def external_agent_upload_interrupted_handler(
        request: Request, _: ExternalAgentUploadInterrupted
    ) -> JSONResponse:
        return error_response(400, "artifact_upload_interrupted", request)

    @app.exception_handler(ContributionConflict)
    async def contribution_conflict_handler(
        request: Request, _: ContributionConflict
    ) -> JSONResponse:
        return error_response(409, "idempotency_conflict", request)

    @app.exception_handler(StaleRevision)
    async def stale_revision_handler(request: Request, _: StaleRevision) -> JSONResponse:
        return error_response(409, "stale_revision", request)

    @app.exception_handler(ExecutionLimitExceeded)
    async def execution_limit_handler(
        request: Request, exception: ExecutionLimitExceeded
    ) -> JSONResponse:
        metrics.increment("polycolab_quota_rejections_total", quota_kind=exception.code)
        response = error_response(429, exception.code, request)
        response.headers["Retry-After"] = str(exception.retry_after_seconds)
        return response

    @app.exception_handler(DomainConflict)
    async def conflict_handler(request: Request, _: DomainConflict) -> JSONResponse:
        return error_response(409, "conflict", request)

    @app.exception_handler(ProposalStale)
    async def proposal_stale_handler(request: Request, exception: ProposalStale) -> JSONResponse:
        response = error_response(409, "stale_proposal", request)
        response.body = json.dumps(
            {
                "error": {
                    "code": "stale_proposal",
                    "request_id": request.state.request_id,
                    "change_id": str(exception.change_id),
                    "current_object_version_id": (
                        str(exception.current_revision_id)
                        if exception.current_revision_id is not None
                        else None
                    ),
                }
            },
            separators=(",", ":"),
        ).encode()
        response.headers["content-length"] = str(len(response.body))
        return response

    @app.exception_handler(InvitationInvalid)
    async def invitation_invalid_handler(request: Request, _: InvitationInvalid) -> JSONResponse:
        return error_response(400, "invalid_invitation", request)

    @app.exception_handler(MembershipTargetInvalid)
    async def membership_target_invalid_handler(
        request: Request, _: MembershipTargetInvalid
    ) -> JSONResponse:
        return error_response(400, "invalid_member", request)

    @app.exception_handler(RecoveryInvalid)
    async def recovery_invalid_handler(request: Request, _: RecoveryInvalid) -> JSONResponse:
        return error_response(400, "invalid_recovery", request)

    @app.exception_handler(RecoveryConflict)
    async def recovery_conflict_handler(request: Request, _: RecoveryConflict) -> JSONResponse:
        return error_response(409, "recovery_conflict", request)

    @app.exception_handler(RecoveryRateLimited)
    async def recovery_rate_handler(request: Request, _: RecoveryRateLimited) -> JSONResponse:
        response = error_response(429, "recovery_rate_limited", request)
        response.headers["Retry-After"] = "3600"
        return response

    @app.exception_handler(RegistrationClosed)
    async def registration_closed_handler(request: Request, _: RegistrationClosed) -> JSONResponse:
        return error_response(403, "registration_closed", request)

    @app.exception_handler(RegistrationSetupRequired)
    async def registration_setup_handler(
        request: Request, _: RegistrationSetupRequired
    ) -> JSONResponse:
        return error_response(409, "setup_required", request)

    @app.exception_handler(AccountAlreadyExists)
    async def registration_conflict_handler(
        request: Request, _: AccountAlreadyExists
    ) -> JSONResponse:
        return error_response(409, "registration_conflict", request)

    @app.exception_handler(RegistrationInvitationInvalid)
    async def registration_invitation_invalid_handler(
        request: Request, _: RegistrationInvitationInvalid
    ) -> JSONResponse:
        return error_response(400, "invalid_registration_invitation", request)

    @app.exception_handler(RegistrationRequestInvalid)
    async def registration_request_invalid_handler(
        request: Request, _: RegistrationRequestInvalid
    ) -> JSONResponse:
        return error_response(422, "registration_request_invalid", request)

    @app.exception_handler(RegistrationInvitationNotFound)
    async def registration_invitation_not_found_handler(
        request: Request, _: RegistrationInvitationNotFound
    ) -> JSONResponse:
        return error_response(404, "not_found", request)

    @app.exception_handler(InvitationDeliveryUnavailable)
    async def invitation_delivery_unavailable_handler(
        request: Request, _: InvitationDeliveryUnavailable
    ) -> JSONResponse:
        return error_response(503, "invitation_delivery_unavailable", request)

    @app.exception_handler(CredentialError)
    async def credential_error_handler(request: Request, _: CredentialError) -> JSONResponse:
        return error_response(503, "credential_unavailable", request)

    from polycolab.agents.routes.runtime import RuntimeApiConflict

    @app.exception_handler(RuntimeApiConflict)
    async def runtime_api_conflict_handler(
        request: Request, exception: RuntimeApiConflict
    ) -> JSONResponse:
        return error_response(409, exception.code, request)

    @app.get("/health/live", include_in_schema=False)
    def live() -> dict[str, str]:
        return {"status": "ok", "service": settings.service_name}

    @app.get("/health/ready", include_in_schema=False)
    def ready(request: Request) -> Response:
        if not database_is_ready(request.app.state.engine):
            metrics.set_gauge("polycolab_db_ready", 0, service=settings.service_name)
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        metrics.set_gauge("polycolab_db_ready", 1, service=settings.service_name)
        return JSONResponse(content={"status": "ok"})

    @app.get("/internal/v1/metrics", include_in_schema=False)
    def operator_metrics(request: Request) -> PlainTextResponse:
        if not settings.operator_diagnostics_enabled:
            raise WorkspaceNotFound
        principal = current_principal(request)
        if principal.subject not in settings.operator_diagnostics_subjects:
            raise AuthorizationDenied
        session = request.app.state.session_factory()
        try:
            durable = render_durable_prometheus(session)
        finally:
            session.close()
        return PlainTextResponse(
            metrics.render_prometheus()
            + durable
            + request.app.state.community_scrape.render()
            + request.app.state.pool_meter.render(request.app.state.engine),
            media_type="text/plain; version=0.0.4; charset=utf-8",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @app.get("/api/reference/content", include_in_schema=False)
    @app.get("/api/reference/config", include_in_schema=False)
    @app.get("/api/reference", include_in_schema=False)
    @app.get("/docs/api/", include_in_schema=False)
    @app.get("/docs/api", include_in_schema=False)
    def api_reference(request: Request) -> Response:
        reference_access = settings.reference_access
        if reference_access is ApiReferenceAccess.DISABLED:
            raise WorkspaceNotFound
        if reference_access is ApiReferenceAccess.OPERATORS:
            principal = current_principal(request)
            if principal.subject not in settings.api_reference_operator_subjects:
                raise AuthorizationDenied
        if request.url.path == "/api/reference":
            return Response(
                status_code=307,
                headers={"Location": "/docs/api/", "Cache-Control": "no-store"},
            )
        if request.url.path == "/docs/api":
            return Response(
                status_code=307,
                headers={"Location": "/docs/api/", "Cache-Control": "no-store"},
            )
        if request.url.path == "/docs/api/" and web_dist is not None:
            documentation_page = web_dist / "docs" / "api" / "index.html"
            response = (
                FileResponse(documentation_page, headers={"X-Content-Type-Options": "nosniff"})
                if documentation_page.is_file()
                else FileResponse(
                    web_dist / "index.html",
                    media_type="text/html",
                    headers={"X-Content-Type-Options": "nosniff"},
                )
            )
            response.headers["Cache-Control"] = "no-store"
            return response
        if request.url.path == "/api/reference/config":
            return JSONResponse(
                scalar_reference_configuration(),
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )
        return HTMLResponse(
            scalar_reference_html(),
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "frame-ancestors 'self'; default-src 'none'; "
                    "script-src 'self' https://cdn.jsdelivr.net; "
                    "connect-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:"
                ),
                "Referrer-Policy": "no-referrer",
            },
        )

    from polycolab.app.router import router

    app.include_router(router)
    from fastapi.routing import APIRoute, iter_route_contexts

    from polycolab.app.route_policy import policy

    api_policies = {
        (route.path, method.lower()): policy(route)
        for route in iter_route_contexts(app.routes)
        if isinstance(route.original_route, APIRoute)
        for method in route.methods or set()
    }
    app.state.public_read_routes = [
        route
        for route in iter_route_contexts(app.routes)
        if isinstance(route.original_route, APIRoute)
        and route.path
        and route.path.startswith("/api/v1/")
        and "GET" in (route.methods or set())
        and policy(route) in {"shared", "anonymous"}
    ]

    web_dist = _web_dist_dir(settings)
    if web_dist is not None and (web_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="web-assets")
    if web_dist is not None and (web_dist / "_app").is_dir():
        app.mount("/_app", StaticFiles(directory=web_dist / "_app"), name="svelte-assets")

    def spa_response(path: str, request: Request) -> Response:
        if _reserved_browser_path(path) or web_dist is None:
            return error_response(404, "not_found", request)
        documentation_redirects = {
            "guide": "/docs/getting-started/",
            "connect": "/docs/setup/external-agent/",
            "docs/connect": "/docs/setup/external-agent/",
            "docs/agent-api": "/docs/developers/agent-runs/",
        }
        if target := documentation_redirects.get(path):
            return Response(status_code=307, headers={"Location": target})
        requested = (web_dist / path).resolve()
        try:
            requested.relative_to(web_dist)
        except ValueError:
            return error_response(404, "not_found", request)
        if path.casefold() == "skill.md":
            if path != "SKILL.md" or not requested.is_file():
                return error_response(404, "not_found", request)
            return FileResponse(
                requested,
                media_type="text/markdown",
                headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
            )
        if path == "docs" or path.startswith("docs/"):
            if requested.is_dir():
                requested = requested / "index.html"
            if not requested.is_file():
                return error_response(404, "not_found", request)
        if path and requested.is_file():
            return FileResponse(requested, headers={"X-Content-Type-Options": "nosniff"})
        return FileResponse(
            web_dist / "index.html",
            media_type="text/html",
            headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
        )

    if web_dist is not None:

        @app.get("/", include_in_schema=False)
        def spa_root(request: Request) -> Response:
            return spa_response("", request)

        @app.get("/{path:path}", include_in_schema=False)
        def spa_fallback(path: str, request: Request) -> Response:
            return spa_response(path, request)

    def custom_openapi() -> dict[str, object]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=API_INTRODUCTION,
            routes=app.routes,
            tags=app.openapi_tags,
        )
        components = schema.setdefault("components", {})
        schemas = components.setdefault("schemas", {})
        schemas["ErrorEnvelope"] = ERROR_ENVELOPE_SCHEMA
        components["securitySchemes"] = {
            "SessionCookie": {
                "type": "apiKey",
                "in": "cookie",
                "name": settings.local_auth_cookie_name,
            },
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "Human OIDC token",
            },
            "ExternalAgentBearer": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "Opaque pca_ credential",
                "description": (
                    "Account-wide external-agent credential; "
                    "live membership and contribution authority apply."
                ),
            },
        }
        for path, path_item in schema.get("paths", {}).items():
            for method, operation in path_item.items():
                if not isinstance(operation, dict):
                    continue
                responses = operation.setdefault("responses", {})
                responses["404"] = _error_response_reference("Not found")
                responses["422"] = _error_response_reference("Validation error")
                operation_id = operation.get("operationId")
                if (
                    isinstance(operation_id, str)
                    and operation_id.startswith("list")
                    and responses.get("200", {})
                    .get("content", {})
                    .get("application/json", {})
                    .get("schema", {})
                    .get("type")
                    == "array"
                ):
                    success = responses.setdefault("200", {"description": "Successful Response"})
                    headers = success.setdefault("headers", {})
                    headers["X-Next-Cursor"] = {
                        "description": "Opaque cursor for the next page, omitted at the end.",
                        "schema": {"type": "string"},
                    }
                    headers["X-Total-Count"] = {
                        "description": "Total items matching the stable listing order.",
                        "schema": {"type": "integer", "minimum": 0},
                    }
                if operation_id == "acceptInvitation":
                    responses["400"] = _error_response_reference("Invalid invitation")
                if operation_id == "createWorkspaceInvitation":
                    responses["503"] = _error_response_reference(
                        "Invitation delivery is unavailable"
                    )
                if operation_id in {
                    "createGatewayProfile",
                    "rotateGatewayProfile",
                    "validateGatewayProfile",
                }:
                    responses["503"] = _error_response_reference(
                        "Credential encryption service is unavailable"
                    )
                responses["429"] = _error_response_reference("Request or mutation budget exhausted")
                responses["500"] = _error_response_reference("Internal error")
                responses["413"] = _error_response_reference("Request too large")
                route_policy = api_policies.get((path, method), "human")
                operation["security"] = (
                    [{}]
                    if route_policy == "anonymous"
                    else [{"ExternalAgentBearer": []}]
                    if route_policy == "agent"
                    else [{"BearerAuth": []}, {"SessionCookie": []}]
                )
                if route_policy == "shared":
                    operation["security"].append({"ExternalAgentBearer": []})
                    if method == "get" and path != "/api/v1/me":
                        operation["security"].append({})
                responses["401"] = _error_response_reference("Authentication required")
                responses["403"] = _error_response_reference("Forbidden")
                responses["409"] = _error_response_reference("Conflict")
        arrange_reference(schema)
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

    # Outermost user middleware: cap actual chunks before request_context.body()
    # can buffer registration input, including requests without Content-Length.
    app.add_middleware(
        RegistrationBodyLimitMiddleware, max_bytes=settings.registration_max_request_bytes
    )
    from polycolab.execution.ingress import RuntimeBodyLimitMiddleware

    app.add_middleware(RuntimeBodyLimitMiddleware, max_bytes=settings.runtime_api_max_request_bytes)
    app.add_middleware(CoreBodyLimitMiddleware, max_bytes=1024 * 1024)
    return app


app = create_app()
