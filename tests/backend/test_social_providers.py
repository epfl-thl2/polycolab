"""Mock-provider and signed-token evidence; no live OAuth application configured."""

import json
from time import time
from typing import cast
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from polycolab.accounts.providers import Provider, SocialAuthenticationFailed, SocialProvider

VERIFIER = "v" * 43
NONCE = "n" * 32


def provider(name: str = "google") -> SocialProvider:
    return SocialProvider(
        cast(Provider, name),
        "test-client",
        "private-secret",
        f"https://app.example/auth/social/{name}/callback",
    )


@pytest.mark.parametrize("name", ["google", "github"])
def test_authorization_is_code_pkce_and_minimal_scope(name: str) -> None:
    configured = provider(name)
    url = configured.authorization_url(state="s" * 32, verifier=VERIFIER, nonce=NONCE)
    query = parse_qs(urlsplit(url).query)
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert "code_verifier" not in query and "private-secret" not in url
    assert "private-secret" not in repr(configured)
    assert query["scope"] == (["openid profile"] if name == "google" else ["read:user"])


def test_github_identity_is_stable_id_not_email_or_login() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "github.com":
            assert request.method == "POST"
            data = parse_qs(request.content.decode())
            assert data["code_verifier"] == [VERIFIER]
            assert data["client_secret"] == ["private-secret"]
            return httpx.Response(
                200, json={"access_token": "secret-token", "token_type": "bearer"}
            )
        assert str(request.url) == "https://api.github.com/user"
        assert request.headers["authorization"] == "Bearer secret-token"
        return httpx.Response(
            200,
            json={"id": 42, "login": "mutable", "email": "victim@example.org", "name": "Example"},
        )

    result = provider("github").exchange(
        code="code", verifier=VERIFIER, nonce=NONCE, transport=httpx.MockTransport(handle)
    )
    assert result.subject == "42" and result.provider == "github"
    assert "email" not in repr(result) and "secret-token" not in repr(result)
    assert len(requests) == 2


@pytest.mark.parametrize(
    "invalid", [None, "issuer", "audience", "nonce", "expiry", "azp", "signature"]
)
def test_google_verifies_signed_identity(invalid: str | None) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "test-key"
    claims = {
        "iss": "https://accounts.google.com",
        "aud": "test-client",
        "sub": "stable-subject",
        "iat": int(time()),
        "exp": int(time()) + 300,
        "nonce": NONCE,
    }
    if invalid == "issuer":
        claims["iss"] = "https://attacker.example"
    if invalid == "audience":
        claims["aud"] = "different-client"
    if invalid == "nonce":
        claims["nonce"] = "wrong"
    if invalid == "expiry":
        claims["exp"] = int(time()) - 10
    if invalid == "azp":
        claims["azp"] = "different-client"
    signing_key = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if invalid == "signature"
        else key
    )
    encoded = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "test-key"})

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"id_token": encoded})
        assert str(request.url) == "https://www.googleapis.com/oauth2/v3/certs"
        return httpx.Response(200, json={"keys": [jwk]})

    def exchange() -> str:
        return (
            provider()
            .exchange(
                code="code", verifier=VERIFIER, nonce=NONCE, transport=httpx.MockTransport(handle)
            )
            .subject
        )

    if invalid is None:
        assert exchange() == "stable-subject"
    else:
        with pytest.raises(SocialAuthenticationFailed, match="^social_authentication_failed$"):
            exchange()


@pytest.mark.parametrize("kind", ["redirect", "oversized", "malformed", "denied", "timeout"])
def test_failures_are_bounded_sanitized_and_not_retried(kind: str) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if kind == "timeout":
            raise httpx.ReadTimeout("private-upstream-body")
        if kind == "redirect":
            return httpx.Response(302, headers={"location": "https://attacker.example"})
        if kind == "oversized":
            return httpx.Response(200, content=b"x" * 65537)
        if kind == "malformed":
            return httpx.Response(200, content=b"private-upstream-body")
        return httpx.Response(200, json={"error": "private-upstream-body"})

    with pytest.raises(SocialAuthenticationFailed) as failure:
        provider().exchange(
            code="code", verifier=VERIFIER, nonce=NONCE, transport=httpx.MockTransport(handle)
        )
    assert str(failure.value) == "social_authentication_failed" and calls == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://app.example/auth/social/google/callback",
        "https://app.example/wrong",
        "https://user:secret@app.example/auth/social/google/callback",
        "https://app.example/auth/social/google/callback?next=bad",
    ],
)
def test_callback_configuration_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValueError):
        SocialProvider("google", "client", "secret", url)
