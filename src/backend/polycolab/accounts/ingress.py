"""Bound registration body buffering before the application request middleware."""

from uuid import UUID, uuid4

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RegistrationBodyLimitMiddleware:
    """Pure ASGI preflight; retain at most max_bytes before replaying downstream.

    Content-Length is only an early rejection hint. Chunked/underdeclared bodies
    are bounded by actual bytes without reading their remainder. Other routes and
    non-HTTP scopes retain their streaming behavior. This is not a network timeout
    or an aggregate connection/memory budget; ingress still owns those limits.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("registration body bound must be a positive integer")
        self.app = app
        self.max_bytes = max_bytes

    def applies(self, scope: Scope) -> bool:
        return (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/auth/register"
        )

    error_code = "registration_request_too_large"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.applies(scope):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        lengths = headers.getlist("content-length")
        if lengths:
            try:
                if len(lengths) != 1:
                    raise ValueError
                declared = int(lengths[0])
                if declared < 0:
                    raise ValueError
            except ValueError:
                await self._reject(scope, receive, send, 400, "invalid_content_length")
                return
            if declared > self.max_bytes:
                await self._reject(scope, receive, send, 413, self.error_code)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await self._reject(scope, receive, send, 413, self.error_code)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send, status: int, code: str) -> None:
        supplied = Headers(scope=scope).get("x-request-id", "")
        try:
            request_id = str(UUID(supplied))
        except ValueError:
            request_id = str(uuid4())
        response = JSONResponse(
            {"error": {"code": code, "request_id": request_id}},
            status_code=status,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Request-ID": request_id,
            },
        )
        await response(scope, receive, send)


class CoreBodyLimitMiddleware(RegistrationBodyLimitMiddleware):
    """Bound JSON writes by actual bytes, independently of claimed Content-Type."""

    error_code = "request_too_large"

    def applies(self, scope: Scope) -> bool:
        import re

        path = scope.get("path", "")
        return (
            scope["type"] == "http"
            and scope.get("method") in {"POST", "PUT", "PATCH"}
            and path.startswith("/api/v1/")
            and not re.fullmatch(r"/api/v1/(?:artifacts|projects/[^/]+/artifacts)", path)
            and not path.startswith("/api/v1/private/")
        )
