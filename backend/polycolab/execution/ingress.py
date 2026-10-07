"""Bound private runtime JSON before buffering it for HTTP dispatch."""

from starlette.types import Scope

from polycolab.accounts.ingress import RegistrationBodyLimitMiddleware


class RuntimeBodyLimitMiddleware(RegistrationBodyLimitMiddleware):
    error_code = "runtime_request_too_large"

    def applies(self, scope: Scope) -> bool:
        return scope["type"] == "http" and str(scope.get("path", "")).startswith(
            "/internal/v1/runtime"
        )
