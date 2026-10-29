"""Deterministic OpenAI-compatible provider used only by integration tests."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def event(payload: dict[str, object]) -> bytes:
    return b"data: " + json.dumps(payload, separators=(",", ":")).encode() + b"\n\n"


class ProviderHandler(BaseHTTPRequestHandler):
    calls: list[dict[str, Any]] = []

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/__test__/calls":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        encoded = json.dumps(self.calls).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        size = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(size))
        self.calls.append(body)
        if body.get("model") == "integration-provider-error":
            self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        messages = body.get("messages", [])
        tool_results = [item for item in messages if item.get("role") == "tool"]
        if not tool_results:
            payload = {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"name": "get_context", "arguments": "{}"}}
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"completion_tokens": 1, "prompt_tokens": 1, "total_tokens": 2},
            }
        else:
            payload = {
                "choices": [
                    {
                        "delta": {"content": "Project context is ready."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"completion_tokens": 2, "prompt_tokens": 3, "total_tokens": 5},
            }
        response = event(payload) + b"data: [DONE]\n\n"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), ProviderHandler).serve_forever()


if __name__ == "__main__":
    main()
