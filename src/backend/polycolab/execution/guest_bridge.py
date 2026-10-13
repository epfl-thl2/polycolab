"""Curated-image entrypoint: multiplex Codex and a loopback Responses proxy.

This code runs INSIDE the untrusted VM. It has no host or provider credentials.
The controller validates every frame independently. It is not a security boundary.
"""

from __future__ import annotations

import base64
import json
import os
import queue
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BYTES = 1_000_000


def main() -> None:
    import guest_repository  # type: ignore[import-not-found]

    repository = guest_repository.checkout()
    output_lock = threading.Lock()
    pending: dict[int, queue.Queue[dict[str, object]]] = {}
    next_request = 0
    pending_lock = threading.Lock()

    def emit(kind: str, payload: object) -> None:
        encoded = json.dumps({"kind": kind, "payload": payload}, separators=(",", ":"))
        with output_lock:
            sys.stdout.write(encoded + "\n")
            sys.stdout.flush()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            nonlocal next_request
            if self.path != "/v1/responses":
                self.send_error(404)
                return
            try:
                count = int(self.headers.get("Content-Length", "0"))
                if not 0 < count <= 262_144:
                    raise ValueError
                body = json.loads(self.rfile.read(count))
                if not isinstance(body, dict):
                    raise ValueError
            except (ValueError, UnicodeError):
                self.send_error(400)
                return
            answer: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
            with pending_lock:
                if pending:
                    self.send_error(429)
                    return
                next_request += 1
                request_id = next_request
                pending[request_id] = answer
            try:
                emit("model", {"id": request_id, "body": body})
                result = answer.get(timeout=60)
                encoded = result.get("body")
                if not isinstance(encoded, str):
                    raise ValueError
                data = base64.b64decode(encoded, validate=True)
                if len(data) > MAX_BYTES:
                    raise ValueError
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (queue.Empty, ValueError, OSError):
                self.close_connection = True
            finally:
                with pending_lock:
                    pending.pop(request_id, None)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    port = server.server_port
    config = Path("/home/agent/.codex")
    config.mkdir(mode=0o700, exist_ok=True)
    (config / "config.toml").write_text(
        'model_provider = "polycolab"\n'
        'approval_policy = "never"\n'
        'web_search = "disabled"\n'
        "[features]\nmulti_agent = false\n"
        "[analytics]\nenabled = false\n"
        '[model_providers.polycolab]\nname = "Polycolab"\n'
        f'base_url = "http://127.0.0.1:{port}/v1"\n'
        'wire_api = "responses"\nrequest_max_retries = 0\n'
        "stream_max_retries = 0\nsupports_websockets = false\n"
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    process = subprocess.Popen(
        ["codex", "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd="/workspace",
        env={
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/home/agent",
            "CODEX_HOME": str(config),
            "LANG": "C.UTF-8",
        },
    )
    assert process.stdin is not None and process.stdout is not None

    def receive_host() -> None:
        assert process.stdin is not None
        for line in sys.stdin.buffer:
            if len(line) > 2 * MAX_BYTES:
                break
            message = json.loads(line)
            if message.get("kind") == "codex":
                process.stdin.write(json.dumps(message["payload"]).encode() + b"\n")
                process.stdin.flush()
            elif message.get("kind") == "repository":
                try:
                    if repository is None:
                        raise ValueError("repository_missing")
                    commit = guest_repository.checkpoint(repository)
                    emit("repository", {"commit": commit})
                except Exception:
                    emit("repository", {"error": "repository_checkpoint_failed"})
            elif message.get("kind") == "model":
                payload = message["payload"]
                with pending_lock:
                    target = pending.get(payload.get("id"))
                if target is not None:
                    target.put_nowait(payload)
        process.kill()

    threading.Thread(target=receive_host, daemon=True).start()
    try:
        while line := process.stdout.readline(MAX_BYTES + 1):
            if len(line) > MAX_BYTES:
                break
            emit("codex", json.loads(line))
    finally:
        process.kill()
        process.wait()
        server.shutdown()
    os._exit(0)


if __name__ == "__main__":
    main()
