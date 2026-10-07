from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

import pytest

from polycolab.model_gateway.transport import (
    ProviderResponse,
    ProviderTransport,
    ProviderTransportError,
    Resolver,
    TransportTimeouts,
)


@dataclass
class RecordingTransport:
    responses: list[ProviderResponse | ProviderTransportError]
    calls: list[dict[str, object]] = field(default_factory=list)

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
        self.calls.append(
            {
                "ip_address": ip_address,
                "scheme": scheme,
                "port": port,
                "host": host,
                "path": path,
                "headers": dict(headers),
                "body": body,
                "timeouts": timeouts,
                "max_response_bytes": max_response_bytes,
            }
        )
        result = self.responses.pop(0)
        if isinstance(result, ProviderTransportError):
            raise result
        return result


def public_resolver(_host: str, _port: int) -> Sequence[str]:
    return ("93.184.216.34",)


PUBLIC_RESOLVER = cast(Resolver, public_resolver)


def no_sleep(_delay: float) -> None:
    pass


def transport(
    responses: list[ProviderResponse | ProviderTransportError],
    *,
    resolver: Resolver = PUBLIC_RESOLVER,
    sleeper: Callable[[float], None] = no_sleep,
    retry_count: int = 1,
    retry_backoff_seconds: float = 0.1,
) -> tuple[ProviderTransport, RecordingTransport]:
    recording = RecordingTransport(responses)
    return (
        ProviderTransport(
            resolver=resolver,
            transport=recording,
            sleeper=sleeper,
            retry_count=retry_count,
            retry_backoff_seconds=retry_backoff_seconds,
        ),
        recording,
    )


def test_request_is_pinned_to_vetted_ip_with_original_host_and_bounded_settings() -> None:
    client, recording = transport([ProviderResponse(200, b'{"id":"ok"}')])

    assert client.request_json(
        base_url="https://provider.example/v1/", api_key="provider-secret", payload={"model": "x"}
    ) == {"id": "ok"}

    call = recording.calls[0]
    assert call["ip_address"] == "93.184.216.34"
    assert call["host"] == "provider.example"
    assert call["scheme"] == "https"
    assert call["path"] == "/v1/chat/completions"
    assert call["headers"] == {
        "authorization": "Bearer provider-secret",
        "content-type": "application/json",
        "accept": "application/json",
    }
    assert call["timeouts"] == TransportTimeouts()
    assert call["max_response_bytes"] == 1_000_000


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "2001:db8::1"],
)
def test_private_or_reserved_resolution_is_rejected_before_egress(address: str) -> None:
    client, recording = transport([], resolver=lambda _host, _port: (address,))

    with pytest.raises(ProviderTransportError, match="unsafe_base_url"):
        client.request_json(base_url="https://provider.example", api_key="secret", payload={})

    assert recording.calls == []


def test_mixed_public_and_private_dns_answer_is_rejected_before_egress() -> None:
    client, recording = transport([], resolver=lambda _host, _port: ("93.184.216.34", "127.0.0.1"))

    with pytest.raises(ProviderTransportError, match="unsafe_base_url"):
        client.request_json(base_url="https://provider.example", api_key="secret", payload={})

    assert recording.calls == []


def test_dns_rebinding_cannot_change_the_selected_egress_ip() -> None:
    resolutions = iter((("93.184.216.34",), ("127.0.0.1",)))
    client, recording = transport(
        [ProviderResponse(200, b"{}")], resolver=lambda _host, _port: next(resolutions)
    )

    assert (
        client.request_json(base_url="https://provider.example", api_key="secret", payload={}) == {}
    )
    assert recording.calls[0]["ip_address"] == "93.184.216.34"
    # The transport receives the selected literal address, so it has no reason
    # to resolve the hostname again and cannot follow a later rebinding.
    assert next(resolutions) == ("127.0.0.1",)


def test_redirect_and_provider_body_are_never_followed_or_leaked() -> None:
    client, _ = transport([ProviderResponse(302, b"secret provider body")])

    with pytest.raises(ProviderTransportError) as raised:
        client.request_json(base_url="https://provider.example", api_key="secret", payload={})

    assert raised.value.code == "provider_redirect_rejected"
    assert "secret" not in str(raised.value)


def test_retries_rate_limits_with_server_owned_backoff() -> None:
    delays: list[float] = []
    client, recording = transport(
        [
            ProviderResponse(429, b"wait"),
            ProviderResponse(429, b"wait"),
            ProviderResponse(200, b"{}"),
        ],
        retry_count=2,
        retry_backoff_seconds=0.25,
        sleeper=delays.append,
    )

    assert (
        client.request_json(base_url="https://provider.example", api_key="secret", payload={}) == {}
    )
    assert len(recording.calls) == 3
    assert delays == [0.25, 0.5]


def test_ambiguous_server_failure_is_not_retried() -> None:
    client, recording = transport([ProviderResponse(503, b"nope")], retry_count=2)

    with pytest.raises(ProviderTransportError, match="provider_request_uncertain"):
        client.request_json(base_url="https://provider.example", api_key="secret", payload={})

    assert len(recording.calls) == 1


def test_response_size_error_is_not_retried() -> None:
    client, recording = transport(
        [ProviderTransportError("provider_response_too_large")], retry_count=2
    )

    with pytest.raises(ProviderTransportError, match="provider_response_too_large"):
        client.request_json(base_url="https://provider.example", api_key="secret", payload={})

    assert len(recording.calls) == 1


def test_ambiguous_post_failure_is_not_retried() -> None:
    client, recording = transport(
        [ProviderTransportError("provider_request_uncertain")], retry_count=2
    )

    with pytest.raises(ProviderTransportError, match="provider_request_uncertain"):
        client.request_json(base_url="https://provider.example", api_key="secret", payload={})

    assert len(recording.calls) == 1
