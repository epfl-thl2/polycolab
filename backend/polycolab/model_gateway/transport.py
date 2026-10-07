"""Secret-safe, IP-pinned transport for OpenAI-compatible providers.

This module deliberately owns only outbound HTTP mechanics.  Credential lookup,
profile ownership, and run-capability checks stay in the gateway domain layer.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import ParseResult, urlparse

import httpcore


class ProviderTransportError(Exception):
    """A stable error code which never includes provider-controlled details."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TransportTimeouts:
    """Explicit finite bounds for a single provider request."""

    connect: float = 5.0
    read: float = 20.0
    write: float = 10.0
    pool: float = 5.0


@dataclass(frozen=True)
class ProviderResponse:
    status_code: int
    body: bytes


@dataclass
class ProviderStreamResponse:
    """A provider response whose body remains bounded and explicitly closable."""

    status_code: int
    chunks: Iterator[bytes]
    _close: Callable[[], None]

    def close(self) -> None:
        self._close()


class Resolver(Protocol):
    def __call__(self, host: str, port: int) -> Sequence[str]: ...


class PinnedTransport(Protocol):
    def request(
        self,
        *,
        ip_address: str,
        scheme: str,
        port: int,
        host: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes,
        timeouts: TransportTimeouts,
        max_response_bytes: int,
    ) -> ProviderResponse: ...


class PinnedStreamTransport(Protocol):
    def open_stream(
        self,
        *,
        ip_address: str,
        scheme: str,
        port: int,
        host: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes,
        timeouts: TransportTimeouts,
        max_response_bytes: int,
    ) -> ProviderStreamResponse: ...


def resolve_addresses(host: str, port: int) -> Sequence[str]:
    """Return addresses once, so the selected address can be pinned for egress."""

    try:
        results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ProviderTransportError("provider_unavailable") from exc
    return tuple(str(result[4][0]) for result in results)


def _public_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ProviderTransportError("unsafe_base_url") from exc
    # `is_global` rejects loopback, RFC1918, link-local, multicast, reserved,
    # unspecified, and documentation ranges.  This is intentionally stricter
    # than selectively enumerating classes that must be denied.
    if not address.is_global:
        raise ProviderTransportError("unsafe_base_url")
    return str(address)


def parse_base_url(value: str) -> tuple[ParseResult, str, int, str]:
    """Validate syntax only; DNS resolution and IP policy occur per request."""

    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ProviderTransportError("unsafe_base_url")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ProviderTransportError("unsafe_base_url") from exc
    if not 1 <= port <= 65535:
        raise ProviderTransportError("unsafe_base_url")
    host = parsed.hostname
    try:
        host.encode("idna")
    except UnicodeError as exc:
        raise ProviderTransportError("unsafe_base_url") from exc
    return parsed, host, port, parsed.scheme


def _request_path(parsed: ParseResult) -> str:
    prefix = parsed.path.rstrip("/")
    if not prefix:
        prefix = ""
    return f"{prefix}/chat/completions"


class HttpcorePinnedTransport:
    """Connect directly to a vetted IP, retaining the original Host and TLS SNI."""

    def request(
        self,
        *,
        ip_address: str,
        scheme: str,
        port: int,
        host: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes,
        timeouts: TransportTimeouts,
        max_response_bytes: int,
    ) -> ProviderResponse:
        authority = f"[{ip_address}]" if ":" in ip_address else ip_address
        request_url = f"{scheme}://{authority}:{port}{path}"
        default_port = 443 if scheme == "https" else 80
        host_header = host if port == default_port else f"{host}:{port}"
        encoded_headers = [(b"host", host_header.encode("idna"))]
        encoded_headers.extend(
            (name.encode("ascii"), value.encode("utf-8")) for name, value in headers.items()
        )
        request = httpcore.Request(
            "POST",
            request_url,
            headers=encoded_headers,
            content=body,
            extensions={
                "sni_hostname": host,
                "timeout": {
                    "connect": timeouts.connect,
                    "read": timeouts.read,
                    "write": timeouts.write,
                    "pool": timeouts.pool,
                },
            },
        )
        pool = httpcore.ConnectionPool(
            max_connections=1,
            max_keepalive_connections=0,
            retries=0,
            http2=False,
        )
        response: httpcore.Response | None = None
        try:
            response = pool.handle_request(request)
            chunks = bytearray()
            for chunk in response.iter_stream():
                if len(chunks) + len(chunk) > max_response_bytes:
                    raise ProviderTransportError("provider_response_too_large")
                chunks.extend(chunk)
            return ProviderResponse(status_code=response.status, body=bytes(chunks))
        except ProviderTransportError:
            raise
        # A connection timeout happens before a request can reach the provider,
        # so the caller may safely retry it.  A read/write failure is ambiguous:
        # the provider may already have accepted this non-idempotent request.
        except (httpcore.ConnectTimeout, httpcore.PoolTimeout) as exc:
            raise ProviderTransportError("provider_timeout") from exc
        except httpcore.ConnectError as exc:
            raise ProviderTransportError("provider_unavailable") from exc
        except (
            httpcore.ReadTimeout,
            httpcore.WriteTimeout,
            httpcore.ReadError,
            httpcore.WriteError,
            httpcore.ProtocolError,
        ) as exc:
            raise ProviderTransportError("provider_request_uncertain") from exc
        finally:
            if response is not None:
                response.close()
            pool.close()

    def open_stream(
        self,
        *,
        ip_address: str,
        scheme: str,
        port: int,
        host: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes,
        timeouts: TransportTimeouts,
        max_response_bytes: int,
    ) -> ProviderStreamResponse:
        """Open a pinned response without buffering its body."""

        authority = f"[{ip_address}]" if ":" in ip_address else ip_address
        request_url = f"{scheme}://{authority}:{port}{path}"
        default_port = 443 if scheme == "https" else 80
        host_header = host if port == default_port else f"{host}:{port}"
        encoded_headers = [(b"host", host_header.encode("idna"))]
        encoded_headers.extend(
            (name.encode("ascii"), value.encode("utf-8")) for name, value in headers.items()
        )
        request = httpcore.Request(
            "POST",
            request_url,
            headers=encoded_headers,
            content=body,
            extensions={
                "sni_hostname": host,
                "timeout": {
                    "connect": timeouts.connect,
                    "read": timeouts.read,
                    "write": timeouts.write,
                    "pool": timeouts.pool,
                },
            },
        )
        pool = httpcore.ConnectionPool(
            max_connections=1,
            max_keepalive_connections=0,
            retries=0,
            http2=False,
        )
        response: httpcore.Response | None = None
        try:
            response = pool.handle_request(request)
            raw_response = response

            def chunks() -> Iterator[bytes]:
                response_bytes = 0
                try:
                    for chunk in raw_response.iter_stream():
                        response_bytes += len(chunk)
                        if response_bytes > max_response_bytes:
                            raise ProviderTransportError("provider_response_too_large")
                        yield chunk
                except ProviderTransportError:
                    raise
                except (
                    httpcore.ReadTimeout,
                    httpcore.WriteTimeout,
                    httpcore.ReadError,
                    httpcore.WriteError,
                    httpcore.ProtocolError,
                ) as exc:
                    raise ProviderTransportError("provider_request_uncertain") from exc

            def close() -> None:
                raw_response.close()
                pool.close()

            return ProviderStreamResponse(response.status, chunks(), close)
        except ProviderTransportError:
            if response is not None:
                response.close()
            pool.close()
            raise
        except (httpcore.ConnectTimeout, httpcore.PoolTimeout) as exc:
            pool.close()
            raise ProviderTransportError("provider_timeout") from exc
        except httpcore.ConnectError as exc:
            pool.close()
            raise ProviderTransportError("provider_unavailable") from exc
        except (
            httpcore.ReadTimeout,
            httpcore.WriteTimeout,
            httpcore.ReadError,
            httpcore.WriteError,
            httpcore.ProtocolError,
        ) as exc:
            pool.close()
            raise ProviderTransportError("provider_request_uncertain") from exc


class ProviderTransport:
    """Bounded synchronous OpenAI-compatible JSON transport.

    The resolver and byte transport are injectable so SSRF and retry behavior
    can be tested deterministically without egress.  The caller never receives
    a provider URL, response body, or credential through an error.
    """

    def __init__(
        self,
        *,
        resolver: Resolver = resolve_addresses,
        transport: PinnedTransport | None = None,
        stream_transport: PinnedStreamTransport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        retry_count: int = 1,
        retry_backoff_seconds: float = 0.1,
        timeouts: TransportTimeouts | None = None,
        max_request_bytes: int = 262_144,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        if retry_count < 0 or retry_count > 3:
            raise ValueError("retry_count must be between 0 and 3")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        if max_request_bytes < 1 or max_response_bytes < 1:
            raise ValueError("request and response byte limits must be positive")
        self._resolver = resolver
        self._transport = transport or HttpcorePinnedTransport()
        self._stream_transport = stream_transport or HttpcorePinnedTransport()
        self._sleeper = sleeper
        self._retry_count = retry_count
        self._retry_backoff_seconds = retry_backoff_seconds
        self._timeouts = timeouts or TransportTimeouts()
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes

    def request_json(
        self,
        *,
        base_url: str,
        api_key: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        parsed, host, port, scheme = parse_base_url(base_url)
        try:
            addresses = self._resolver(host, port)
        except ProviderTransportError:
            raise
        except OSError as exc:
            raise ProviderTransportError("provider_unavailable") from exc
        if not addresses:
            raise ProviderTransportError("unsafe_base_url")
        # Reject a mixed DNS answer as well.  Selecting a public address today
        # while retaining a private alternative would make the allow decision
        # sensitive to resolver ordering on a future attempt.
        vetted_addresses = tuple(_public_ip(address) for address in addresses)
        vetted_address = vetted_addresses[0]
        try:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ProviderTransportError("provider_request_invalid") from exc
        if len(body) > self._max_request_bytes:
            raise ProviderTransportError("gateway_input_limit_exceeded")
        headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
            "accept": "application/json",
        }
        for attempt in range(self._retry_count + 1):
            try:
                response = self._transport.request(
                    ip_address=vetted_address,
                    scheme=scheme,
                    port=port,
                    host=host,
                    path=_request_path(parsed),
                    headers=headers,
                    body=body,
                    timeouts=self._timeouts,
                    max_response_bytes=self._max_response_bytes,
                )
            except ProviderTransportError as exc:
                if exc.code not in {"provider_timeout", "provider_unavailable"}:
                    raise
                if attempt == self._retry_count:
                    raise
                self._sleeper(self._retry_backoff_seconds * (2**attempt))
                continue
            if response.status_code == 429:
                if attempt == self._retry_count:
                    raise ProviderTransportError("provider_rate_limited")
                self._sleeper(self._retry_backoff_seconds * (2**attempt))
                continue
            # A 5xx response to a non-idempotent generation request is
            # ambiguous: the provider may already have completed or billed it.
            if 500 <= response.status_code < 600:
                raise ProviderTransportError("provider_request_uncertain")
            if 300 <= response.status_code < 400:
                raise ProviderTransportError("provider_redirect_rejected")
            if response.status_code >= 400:
                raise ProviderTransportError("provider_rejected")
            try:
                decoded = json.loads(response.body)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProviderTransportError("provider_invalid_response") from exc
            if not isinstance(decoded, dict):
                raise ProviderTransportError("provider_invalid_response")
            return decoded
        raise AssertionError("bounded retry loop must return or raise")

    def open_stream(
        self,
        *,
        base_url: str,
        api_key: str,
        payload: Mapping[str, object],
        responses: bool = False,
    ) -> ProviderStreamResponse:
        """Open a bounded SSE response; never retries an ambiguous stream."""

        parsed, host, port, scheme = parse_base_url(base_url)
        try:
            addresses = self._resolver(host, port)
        except ProviderTransportError:
            raise
        except OSError as exc:
            raise ProviderTransportError("provider_unavailable") from exc
        if not addresses:
            raise ProviderTransportError("unsafe_base_url")
        vetted_addresses = tuple(_public_ip(address) for address in addresses)
        vetted_address = vetted_addresses[0]
        try:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ProviderTransportError("provider_request_invalid") from exc
        if len(body) > self._max_request_bytes:
            raise ProviderTransportError("gateway_input_limit_exceeded")
        headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        retries = 0 if responses else self._retry_count
        for attempt in range(retries + 1):
            try:
                response = self._stream_transport.open_stream(
                    ip_address=vetted_address,
                    scheme=scheme,
                    port=port,
                    host=host,
                    path=(parsed.path.rstrip("/") + "/responses")
                    if responses
                    else _request_path(parsed),
                    headers=headers,
                    body=body,
                    timeouts=self._timeouts,
                    max_response_bytes=self._max_response_bytes,
                )
            except ProviderTransportError as exc:
                if exc.code not in {"provider_timeout", "provider_unavailable"}:
                    raise
                if attempt == retries:
                    raise
                self._sleeper(self._retry_backoff_seconds * (2**attempt))
                continue
            if response.status_code == 429:
                response.close()
                if attempt == retries:
                    raise ProviderTransportError("provider_rate_limited")
                self._sleeper(self._retry_backoff_seconds * (2**attempt))
                continue
            if 500 <= response.status_code < 600:
                response.close()
                raise ProviderTransportError("provider_request_uncertain")
            if 300 <= response.status_code < 400:
                response.close()
                raise ProviderTransportError("provider_redirect_rejected")
            if response.status_code >= 400:
                response.close()
                raise ProviderTransportError("provider_rejected")
            return response
        raise AssertionError("bounded stream retry loop must return or raise")
