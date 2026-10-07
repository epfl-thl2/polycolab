"""Cancellable IP-pinned Responses transport; one request, no redirects or retries."""

from __future__ import annotations

import asyncio
import json

import httpcore

from polycolab.model_gateway.transport import (
    ProviderTransportError,
    _public_ip,
    parse_base_url,
    resolve_addresses,
)


async def responses(
    *, base_url: str, api_key: str, payload: dict[str, object], max_bytes: int
) -> bytes:
    parsed, host, port, scheme = parse_base_url(base_url)
    addresses = await asyncio.to_thread(resolve_addresses, host, port)
    if not addresses:
        raise ProviderTransportError("unsafe_base_url")
    vetted = tuple(_public_ip(item) for item in addresses)
    ip = vetted[0]
    authority = f"[{ip}]" if ":" in ip else ip
    host_header = host if port == (443 if scheme == "https" else 80) else f"{host}:{port}"
    try:
        async with httpcore.AsyncConnectionPool(max_connections=1, retries=0) as pool:
            async with pool.stream(
                "POST",
                f"{scheme}://{authority}:{port}{parsed.path.rstrip('/')}/responses",
                headers={
                    "host": host_header,
                    "authorization": f"Bearer {api_key}",
                    "content-type": "application/json",
                    "accept": "text/event-stream",
                    "accept-encoding": "identity",
                },
                content=json.dumps(payload, separators=(",", ":")).encode(),
                extensions={
                    "sni_hostname": host,
                    "timeout": {"connect": 5, "read": 20, "write": 10, "pool": 5},
                },
            ) as response:
                if response.status != 200:
                    raise ProviderTransportError(
                        "provider_request_uncertain"
                        if response.status >= 500
                        else "provider_rejected"
                    )
                if any(
                    k.lower() == b"content-encoding" and v.lower() != b"identity"
                    for k, v in response.headers
                ):
                    raise ProviderTransportError("provider_encoding_unsupported")
                data = bytearray()
                async for chunk in response.aiter_stream():
                    if len(data) + len(chunk) > max_bytes:
                        raise ProviderTransportError("provider_response_too_large")
                    data.extend(chunk)
                return bytes(data)
    except httpcore.NetworkError, httpcore.TimeoutException, httpcore.ProtocolError:
        raise ProviderTransportError("provider_request_uncertain") from None
