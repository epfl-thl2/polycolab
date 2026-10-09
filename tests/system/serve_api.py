"""Test-only API entrypoint for the local integrated acceptance harness.

It is deliberately outside ``src/backend``: production configuration cannot
select this identity verifier or the loopback provider transport.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator

import httpx
import uvicorn
from fastapi import Request

from polycolab.accounts.authentication import (
    LocalSessionVerifier,
    MappingIdentityVerifier,
    Principal,
)
from polycolab.accounts.builtin import bootstrap_admin
from polycolab.app.application import create_app
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.model_gateway.transport import (
    PinnedStreamTransport,
    PinnedTransport,
    ProviderResponse,
    ProviderStreamResponse,
    ProviderTransport,
    TransportTimeouts,
)
from polycolab.platform.config import AuthMode, Environment, RegistrationMode, Settings


class LoopbackProviderTransport(PinnedTransport, PinnedStreamTransport):
    """Exercise OpenAI wire format without permitting local-provider egress.

    ``ProviderTransport`` still validates a global profile address. This test
    transport receives that already-vetted request and forwards it only to the
    local deterministic provider supplied on the command line.
    """

    def __init__(self, provider_url: str) -> None:
        self._provider_url = provider_url.rstrip("/") + "/v1/chat/completions"

    def request(
        self,
        *,
        ip_address: str,
        scheme: str,
        port: int,
        host: str,
        path: str,
        headers: dict[str, str],
        body: bytes,
        timeouts: TransportTimeouts,
        max_response_bytes: int,
    ) -> ProviderResponse:
        del ip_address, scheme, port, host, path, max_response_bytes
        response = httpx.post(
            self._provider_url,
            headers=headers,
            content=body,
            timeout=timeouts.read,
            trust_env=False,
            follow_redirects=False,
        )
        return ProviderResponse(status_code=response.status_code, body=response.content)

    def open_stream(
        self,
        *,
        ip_address: str,
        scheme: str,
        port: int,
        host: str,
        path: str,
        headers: dict[str, str],
        body: bytes,
        timeouts: TransportTimeouts,
        max_response_bytes: int,
    ) -> ProviderStreamResponse:
        del ip_address, scheme, port, host, path, max_response_bytes
        client = httpx.Client(timeout=timeouts.read, trust_env=False, follow_redirects=False)
        context = client.stream("POST", self._provider_url, headers=headers, content=body)
        response = context.__enter__()

        def chunks() -> Iterator[bytes]:
            try:
                yield from response.iter_bytes()
            finally:
                context.__exit__(None, None, None)
                client.close()

        return ProviderStreamResponse(response.status_code, chunks(), client.close)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--provider-url", required=True)
    parser.add_argument("--port", type=int, default=18000)
    parser.add_argument("--web-origin", default="http://127.0.0.1:13000")
    parser.add_argument(
        "--registration-mode",
        choices=[mode.value for mode in RegistrationMode],
        default=RegistrationMode.CLOSED.value,
    )
    args = parser.parse_args()
    registration_mode = RegistrationMode(args.registration_mode)
    settings = Settings(
        app_env=Environment.LOCAL,
        auth_mode=AuthMode.LOCAL,
        registration_mode=registration_mode,
        registration_requests_per_minute=20,
        public_app_origin=(
            args.web_origin if registration_mode is not RegistrationMode.CLOSED else None
        ),
        database_url=args.database_url,
        allowed_origins=[args.web_origin],
        local_credential_master_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        runtime_sse_poll_seconds=0.05,
        runtime_sse_heartbeat_seconds=5,
        gateway_retry_count=0,
    )
    verifier = MappingIdentityVerifier(
        {
            name: Principal(
                "https://integration.polycolab.test", name, f"{name}@example.test", name.title()
            )
            for name in ("owner", "contributor", "reader", "outsider")
        }
    )
    app = create_app(settings, verifier)
    with app.state.session_factory() as session:
        bootstrap_admin(SqlAlchemyTransaction(session), "registration-admin-password")
    # Keep bearer fixtures for older system tests and exercise real local cookie
    # authentication for the production Svelte journey. This adapter is test-only.
    local_verifier = LocalSessionVerifier(app.state.session_factory, settings)

    class BrowserAndFixtureVerifier:
        def verify(self, authorization: str | None) -> Principal | None:
            return verifier.verify(authorization)

        def verify_request(self, request: Request) -> Principal | None:
            if request.headers.get("Authorization"):
                return verifier.verify_request(request)
            return local_verifier.verify_request(request)

    app.state.identity_verifier = BrowserAndFixtureVerifier()
    # The resolver result remains globally routable, preserving the profile and
    # transport policy paths while the pinned byte transport is test-local.
    loopback = LoopbackProviderTransport(args.provider_url)
    app.state.provider_transport = ProviderTransport(
        resolver=lambda _host, _port: ("8.8.8.8",),
        transport=loopback,
        stream_transport=loopback,
        retry_count=0,
        max_response_bytes=settings.gateway_max_response_bytes,
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
