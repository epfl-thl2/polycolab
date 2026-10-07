"""Bound request bodies before JSON parsing, including chunked requests."""

import asyncio

from fastapi import HTTPException
from fastapi.routing import APIRoute
from pydantic import ValidationError
from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from polycolab.verification.contracts import VerificationInputInvalid


class VerificationRoute(APIRoute):
    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        settings = scope["app"].state.settings
        binary = scope["method"] == "PUT" and scope["path"].endswith("/outputs")
        ceiling = (
            settings.artifact_max_bytes if binary else settings.verification_api_max_request_bytes
        )
        total = 0

        async def bounded_receive() -> Message:
            nonlocal total
            try:
                message = await asyncio.wait_for(receive(), timeout=30)
            except TimeoutError:
                raise HTTPException(408, "verification_request_timeout") from None
            total += len(message.get("body", b""))
            if total > ceiling:
                raise HTTPException(413, "verification_request_too_large")
            return message

        suppressed = False

        async def bounded_send(message: Message) -> None:
            nonlocal suppressed
            if suppressed:
                return
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                if (
                    headers.get(b"content-type", b"").startswith(b"application/json")
                    and int(headers.get(b"content-length", b"0"))
                    > settings.verification_api_max_response_bytes
                ):
                    suppressed = True
                    await JSONResponse(
                        {"detail": "verification_response_too_large"},
                        status_code=503,
                        headers={"Cache-Control": "private, no-store"},
                    )(scope, receive, send)
                    return
            await send(message)

        try:
            await super().handle(scope, bounded_receive, bounded_send)
        except VerificationInputInvalid, ValidationError:
            raise HTTPException(422, "invalid_verification_input") from None
