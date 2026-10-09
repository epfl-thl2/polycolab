"""Identity boundary. Production OIDC verification can replace this adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Protocol
from uuid import UUID

import jwt
from fastapi import Depends, Request
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor, human_actor
from polycolab.accounts.builtin import account_for_session
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.accounts import Principal as Principal
from polycolab.platform.config import AuthMode, Settings


class IdentityVerifier(Protocol):
    """Verifies a provider-issued bearer token without leaking provider details."""

    def verify(self, authorization: str | None) -> Principal | None: ...

    def verify_request(self, request: Request) -> Principal | None: ...


class UnconfiguredOidcJwtVerifier:
    """Fail closed until the deployment supplies a managed OIDC verifier.

    OIDC JWT verification intentionally remains an adapter concern. This
    default never trusts browser-provided identity claims.
    """

    def verify(self, authorization: str | None) -> Principal | None:
        del authorization
        return None

    def verify_request(self, request: Request) -> Principal | None:
        return self.verify(request.headers.get("Authorization"))


class OidcJwtVerifier:
    """Provider-neutral OIDC verifier with a pinned issuer/JWKS trust boundary."""

    def __init__(self, settings: Settings) -> None:
        if settings.oidc_issuer is None or settings.oidc_jwks_url is None:
            raise ValueError("OIDC issuer and JWKS URL must be configured")
        self._issuer = str(settings.oidc_issuer).rstrip("/")
        self._audience = settings.oidc_audience
        self._authorized_party = settings.oidc_authorized_party
        self._leeway = settings.oidc_clock_skew_seconds
        self._jwks = PyJWKClient(
            str(settings.oidc_jwks_url), cache_keys=True, lifespan=300, timeout=5
        )

    def verify(self, authorization: str | None) -> Principal | None:
        token = bearer_token(authorization)
        if token is None:
            return None
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={
                    "require": ["exp", "iat", "iss", "sub"],
                    "verify_aud": self._audience is not None,
                },
            )
        # Unknown key IDs trigger PyJWKClient's cache refresh. Key fetch and all
        # validation failures intentionally collapse to a generic 401 response.
        except Exception:
            return None
        if self._authorized_party is not None and claims.get("azp") != self._authorized_party:
            return None
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            return None
        email = claims.get("email")
        name = claims.get("name")
        return Principal(
            issuer=self._issuer,
            subject=subject,
            email=email if isinstance(email, str) else None,
            display_name=name if isinstance(name, str) else None,
        )

    def verify_request(self, request: Request) -> Principal | None:
        return self.verify(request.headers.get("Authorization"))


class LocalSessionVerifier:
    """Resolve an opaque, database-backed browser session into a Principal."""

    def __init__(self, session_factory: Callable[[], Session], settings: Settings) -> None:
        self._session_factory = session_factory
        self._cookie_name = settings.local_auth_cookie_name

    def verify(self, authorization: str | None) -> Principal | None:
        # Local browser sessions intentionally cannot be supplied as bearer tokens.
        del authorization
        return None

    def verify_request(self, request: Request) -> Principal | None:
        token = request.cookies.get(self._cookie_name)
        if not token or len(token) > 512:
            return None
        session = self._session_factory()
        try:
            account = account_for_session(SqlAlchemyTransaction(session), token)
        finally:
            session.close()
        if account is None:
            return None
        return Principal(
            issuer="polycolab-local",
            subject=str(account.id),
            display_name=account.display_name or account.username,
        )


def verifier_from_settings(
    settings: Settings, session_factory: Callable[[], Session] | None = None
) -> IdentityVerifier:
    if settings.auth_mode is AuthMode.LOCAL:
        if session_factory is None:
            raise ValueError("local authentication requires a database session factory")
        return LocalSessionVerifier(session_factory, settings)
    if settings.oidc_issuer is None or settings.oidc_jwks_url is None:
        return UnconfiguredOidcJwtVerifier()
    return OidcJwtVerifier(settings)


class MappingIdentityVerifier:
    """In-memory test adapter; it is injected by tests and never configured by env."""

    def __init__(self, principals: dict[str, Principal]) -> None:
        self._principals = principals

    def verify(self, authorization: str | None) -> Principal | None:
        token = bearer_token(authorization)
        if token is None:
            return None
        return self._principals.get(token)

    def verify_request(self, request: Request) -> Principal | None:
        return self.verify(request.headers.get("Authorization"))


def bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.casefold() != "bearer" or not token or " " in token:
        return None
    return token


class AuthenticationRequired(Exception):
    pass


def current_principal(request: Request) -> Principal:
    verifier: IdentityVerifier = request.app.state.identity_verifier
    principal = (
        verifier.verify(request.headers.get("authorization"))
        if "authorization" in request.headers
        else verifier.verify_request(request)
    )
    if principal is None:
        raise AuthenticationRequired
    return principal


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def human_actor_from_verified_principal(*, principal: Principal, user_id: UUID) -> Actor:
    """Build a human actor only after authentication and user resolution."""

    if not principal.issuer or not principal.subject:
        raise AuthenticationRequired
    return human_actor(user_id)
