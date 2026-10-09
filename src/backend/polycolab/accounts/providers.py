"""Bounded Google/GitHub identity exchange, independent of account persistence.

Call exchange only after consuming browser-bound, unexpired OAuth state. This
module does not authenticate an application session or link/create an account.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from time import monotonic
from typing import Literal
from urllib.parse import urlencode

import httpx
import jwt

Provider = Literal["google", "github"]
_AUTH = {
    "google": "https://accounts.google.com/o/oauth2/v2/auth",
    "github": "https://github.com/login/oauth/authorize",
}
_TOKEN = {
    "google": "https://oauth2.googleapis.com/token",
    "github": "https://github.com/login/oauth/access_token",
}
_GOOGLE_KEYS = "https://www.googleapis.com/oauth2/v3/certs"
_GITHUB_USER = "https://api.github.com/user"


class SocialAuthenticationFailed(Exception):
    """Sanitized authentication failure; never return upstream responses."""


@dataclass(frozen=True)
class SocialIdentity:
    provider: Provider
    subject: str
    display_name: str | None


@dataclass(frozen=True)
class SocialProvider:
    provider: Provider
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str
    allow_loopback_http: bool = False

    def __post_init__(self) -> None:
        url = httpx.URL(self.redirect_uri)
        if (
            self.provider not in _AUTH
            or not 1 <= len(self.client_id) <= 500
            or not 1 <= len(self.client_secret) <= 4096
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
            or url.path != f"/auth/social/{self.provider}/callback"
            or not (
                url.scheme == "https"
                or (
                    self.allow_loopback_http
                    and url.scheme == "http"
                    and url.host in {"localhost", "127.0.0.1", "::1"}
                )
            )
        ):
            raise ValueError("invalid social provider configuration")

    def authorization_url(self, *, state: str, verifier: str, nonce: str) -> str:
        _validate_flow(state=state, verifier=verifier, nonce=nonce)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        parameters = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "state": state,
            "code_challenge": challenge.decode("ascii").rstrip("="),
            "code_challenge_method": "S256",
            "scope": "openid profile" if self.provider == "google" else "read:user",
        }
        if self.provider == "google":
            parameters["nonce"] = nonce
        return _AUTH[self.provider] + "?" + urlencode(parameters)

    def exchange(
        self,
        *,
        code: str,
        verifier: str,
        nonce: str,
        transport: httpx.BaseTransport | None = None,
    ) -> SocialIdentity:
        try:
            _validate_flow(state="s" * 32, verifier=verifier, nonce=nonce)
            if not code or len(code) > 4096:
                raise ValueError("invalid code")
            # New isolated client: no ambient proxy, cookies, credentials or retries.
            with httpx.Client(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(10, connect=3),
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "User-Agent": "Polycolab",
                },
            ) as client:
                token = _json(
                    client,
                    "POST",
                    _TOKEN[self.provider],
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "redirect_uri": self.redirect_uri,
                        "code": code,
                        "code_verifier": verifier,
                        "grant_type": "authorization_code",
                    },
                )
                if "error" in token:
                    raise ValueError("provider denied exchange")
                if self.provider == "google":
                    identity_token = token.get("id_token")
                    if not isinstance(identity_token, str) or len(identity_token) > 16384:
                        raise ValueError("missing identity token")
                    claims = self._google_claims(client, identity_token, nonce)
                    subject = claims.get("sub")
                    if not isinstance(subject, str) or not 1 <= len(subject) <= 255:
                        raise ValueError("invalid subject")
                    return SocialIdentity("google", subject, _name(claims.get("name")))
                access_token = token.get("access_token")
                if (
                    not isinstance(access_token, str)
                    or not re.fullmatch(r"[A-Za-z0-9_.~-]{1,4096}", access_token)
                    or str(token.get("token_type", "")).lower() != "bearer"
                ):
                    raise ValueError("invalid access token")
                profile = _json(
                    client,
                    "GET",
                    _GITHUB_USER,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                    },
                )
                user_id = profile.get("id")
                if type(user_id) is not int or not 1 <= user_id <= 2**63 - 1:
                    raise ValueError("invalid subject")
                return SocialIdentity("github", str(user_id), _name(profile.get("name")))
        except Exception:
            raise SocialAuthenticationFailed("social_authentication_failed") from None

    def _google_claims(self, client: httpx.Client, token: str, nonce: str) -> dict[str, object]:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str) or not 1 <= len(kid) <= 200:
            raise ValueError("invalid token header")
        keys = _json(client, "GET", _GOOGLE_KEYS).get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 20:
            raise ValueError("invalid keys")
        matches = [key for key in keys if isinstance(key, dict) and key.get("kid") == kid]
        if len(matches) != 1 or matches[0].get("kty") != "RSA":
            raise ValueError("unknown signing key")
        key = jwt.PyJWK.from_dict(matches[0], algorithm="RS256")
        claims: dict[str, object] = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=self.client_id,
            issuer=["https://accounts.google.com", "accounts.google.com"],
            options={"require": ["iss", "aud", "sub", "exp", "iat", "nonce"]},
        )
        actual_nonce = claims.get("nonce")
        if not isinstance(actual_nonce, str) or not hmac.compare_digest(actual_nonce, nonce):
            raise ValueError("nonce mismatch")
        audience = claims.get("aud")
        if (
            "azp" in claims
            and claims["azp"] != self.client_id
            or isinstance(audience, list)
            and len(audience) > 1
            and claims.get("azp") != self.client_id
        ):
            raise ValueError("authorized party mismatch")
        return claims


def _validate_flow(*, state: str, verifier: str, nonce: str) -> None:
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", state)
        or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
        or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", nonce)
    ):
        raise ValueError("invalid OAuth flow values")


def _name(value: object) -> str | None:
    return value if isinstance(value, str) and 1 <= len(value) <= 200 else None


def _json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    # kwargs contain form data or headers only; no provider-supplied URL is used.
    started = monotonic()
    client.cookies.clear()
    with client.stream(method, url, data=data, headers=headers) as response:
        if (
            response.status_code != 200
            or response.headers.get("content-encoding", "identity") != "identity"
        ):
            raise ValueError("invalid provider response")
        body = bytearray()
        for chunk in response.iter_bytes():
            if monotonic() - started > 20 or len(body) + len(chunk) > 65536:
                raise ValueError("oversized provider response")
            body.extend(chunk)
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("invalid provider JSON")
        return value
