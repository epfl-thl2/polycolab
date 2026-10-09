"""Explicit, version-pinned OpenBao Transit envelope-key adapter.

Application API only. Provisioning/rotation/configuration are operator concerns;
this adapter never creates, exports, rotates or deletes Transit keys.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import re
import time
from urllib.parse import urlsplit

import httpx

from polycolab.model_gateway.credentials import CredentialError


class OpenBaoKeyWrapper:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        backend_id: str,
        environment: str,
        key_name: str,
        transit_version: int,
        mount: str = "transit",
        allow_loopback_http: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        try:
            loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
        except ValueError:
            loopback = parsed.hostname == "localhost"
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.scheme not in {"https", "http"}
            or (parsed.scheme != "https" and not (allow_loopback_http and loopback))
        ):
            raise ValueError("OpenBao requires an explicit HTTPS origin")
        if not token or len(token) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError("invalid explicit OpenBao credential")
        if any(
            re.fullmatch(r"[A-Za-z0-9_-]{1,32}", value) is None
            for value in (backend_id, environment, mount, key_name)
        ):
            raise ValueError("invalid OpenBao key identity")
        if type(transit_version) is not int or not 1 <= transit_version <= 2**31 - 1:
            raise ValueError("a finite positive Transit version is required")
        self.backend_id = backend_id
        self.environment = environment
        self.mount = mount
        self.key_name = key_name
        self.transit_version = transit_version
        self._key_version = (
            f"openbao:v1:{backend_id}:{environment}:{mount}:{key_name}:{transit_version}"
        )
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-Vault-Token": token},
            timeout=httpx.Timeout(3, connect=3, read=3, write=3, pool=3),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )

    @property
    def key_version(self) -> str:
        return self._key_version

    def close(self) -> None:
        self._client.close()

    def _context(self, context: bytes) -> str:
        if not 1 <= len(context) <= 2048:
            raise CredentialError("credential_context_invalid")
        value = json.dumps(
            [
                "polycolab-transit-context-v1",
                self.backend_id,
                self.environment,
                self.mount,
                self.key_name,
                base64.b64encode(context).decode("ascii"),
            ],
            separators=(",", ":"),
        ).encode("ascii")
        return base64.b64encode(value).decode("ascii")

    def _request(
        self, method: str, operation: str, payload: dict[str, object] | None = None
    ) -> dict[str, object]:
        data = json.dumps(payload, separators=(",", ":")).encode() if payload else None
        if data is not None and len(data) > 16384:
            raise CredentialError("key_service_request_invalid")
        deadline = time.monotonic() + 10
        try:
            with self._client.stream(
                method,
                f"/v1/{self.mount}/{operation}/{self.key_name}",
                content=data,
                headers={"Content-Type": "application/json", "Accept-Encoding": "identity"},
            ) as response:
                if (
                    response.status_code != 200
                    or response.headers.get("content-encoding", "identity") != "identity"
                ):
                    raise CredentialError("key_service_unavailable")
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > 16384 or time.monotonic() >= deadline:
                        raise CredentialError("key_service_response_invalid")
                    body.extend(chunk)
            value = json.loads(body)
            if not isinstance(value, dict) or not isinstance(value.get("data"), dict):
                raise CredentialError("key_service_response_invalid")
            return dict(value["data"])
        except httpx.HTTPError, ValueError, UnicodeError:
            # Suppress exception chaining: HTTP errors may contain server bodies.
            raise CredentialError("key_service_unavailable") from None

    def check_policy(self) -> None:
        """Read only exact key metadata; never upsert an absent key."""
        policy = self._request("GET", "keys")
        keys = policy.get("keys")
        if (
            policy.get("type") != "aes256-gcm96"
            or policy.get("derived") is not True
            or policy.get("exportable") is not False
            or policy.get("allow_plaintext_backup") is not False
            or policy.get("deletion_allowed") is not False
            or policy.get("convergent_encryption", False) is not False
            or not isinstance(keys, dict)
            or str(self.transit_version) not in keys
        ):
            raise CredentialError("key_service_policy_invalid")

    def _ciphertext(self, value: object) -> bytes:
        if not isinstance(value, str) or len(value) > 4096:
            raise CredentialError("wrapped_key_invalid")
        prefix = f"vault:v{self.transit_version}:"
        if not value.startswith(prefix):
            raise CredentialError("credential_key_version_unavailable")
        try:
            decoded = base64.b64decode(value[len(prefix) :], validate=True)
            # aes256-gcm96: 12-byte nonce + 32-byte DEK + 16-byte tag.
            if len(decoded) != 60:
                raise ValueError
            return value.encode("ascii")
        except ValueError, UnicodeError:
            raise CredentialError("wrapped_key_invalid") from None

    def wrap(self, plaintext_key: bytes, context: bytes) -> bytes:
        if len(plaintext_key) != 32:
            raise CredentialError("credential_data_key_invalid")
        encoded_context = self._context(context)
        self.check_policy()
        result = self._request(
            "POST",
            "encrypt",
            {
                "plaintext": base64.b64encode(plaintext_key).decode("ascii"),
                "context": encoded_context,
                "associated_data": encoded_context,
                "key_version": self.transit_version,
            },
        )
        return self._ciphertext(result.get("ciphertext"))

    def unwrap(self, wrapped_key: bytes, context: bytes) -> bytes:
        if len(wrapped_key) > 4096:
            raise CredentialError("wrapped_key_invalid")
        try:
            ciphertext = self._ciphertext(wrapped_key.decode("ascii")).decode("ascii")
        except UnicodeError:
            raise CredentialError("wrapped_key_invalid") from None
        encoded_context = self._context(context)
        self.check_policy()
        result = self._request(
            "POST",
            "decrypt",
            {
                "ciphertext": ciphertext,
                "context": encoded_context,
                "associated_data": encoded_context,
            },
        )
        try:
            encoded = result.get("plaintext")
            if not isinstance(encoded, str) or len(encoded) != 44:
                raise ValueError
            key = base64.b64decode(encoded, validate=True)
            if len(key) != 32:
                raise ValueError
            return key
        except ValueError, UnicodeError:
            raise CredentialError("credential_data_key_invalid") from None
