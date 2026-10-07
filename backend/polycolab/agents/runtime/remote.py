"""Stateless built-in worker using only private Application API contracts."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, Protocol, cast
from uuid import UUID

import httpx

from polycolab.agents.runtime.contracts import ModelGateway, ModelStreamFrame, ModelTurn, ToolCall
from polycolab.agents.runtime.gateways import ModelGatewayError, ToolGateway, ToolGatewayError

WorkerEventKind = Literal["ASSISTANT_DELTA", "TOOL_REQUESTED", "TOOL_RESULT"]
WorkerTerminalStatus = Literal["COMPLETED", "CANCELLED", "FAILED", "TIMED_OUT"]


class RuntimeGatewayError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RuntimeClaim:
    run_id: UUID
    lease_generation: int
    model_id: str
    messages: list[dict[str, object]]
    tool_capability: str
    max_output_tokens: int
    max_model_rounds: int
    max_tool_calls: int
    max_tool_argument_bytes: int
    max_tool_result_bytes: int
    lease_for: timedelta
    deadline_at: datetime | None = None
    runtime_spec: dict[str, object] | None = None
    tools: list[dict[str, object]] = field(default_factory=list)
    input_manifest: list[dict[str, object]] = field(default_factory=list)
    server_time: datetime | None = None
    repository: dict[str, str] | None = None


@dataclass(frozen=True)
class RuntimeLeaseState:
    cancel_requested: bool
    timed_out: bool


class RuntimeGateway(Protocol):
    def claim(self, *, worker_id: str) -> RuntimeClaim | None: ...

    def heartbeat(
        self, *, run_id: UUID, worker_id: str, lease_generation: int
    ) -> RuntimeLeaseState: ...

    def issue_model_grant(self, *, run_id: UUID, worker_id: str, lease_generation: int) -> str: ...

    def append_event(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        lease_generation: int,
        idempotency_key: str,
        kind: WorkerEventKind,
        payload: dict[str, object],
    ) -> int: ...

    def record_usage(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        lease_generation: int,
        idempotency_key: str,
        frame: ModelStreamFrame,
    ) -> None: ...

    def finish(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        lease_generation: int,
        status: WorkerTerminalStatus,
        failure_code: str | None,
        final_message_md: str | None = None,
    ) -> None: ...


class HttpRuntimeGateway:
    """Strict client for the private, worker-authenticated Runtime API."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str,
        timeout_seconds: float = 10.0,
        max_request_bytes: int = 262_144,
        max_response_bytes: int = 2_000_000,
        engine: Literal["builtin", "codex"] = "builtin",
    ) -> None:
        if not base_url or not token or timeout_seconds <= 0:
            raise ValueError("runtime API URL, token, and positive timeout are required")
        if min(max_request_bytes, max_response_bytes) < 1:
            raise ValueError("runtime API payload limits must be positive")
        self.engine = engine
        self._url = base_url.rstrip("/") + "/internal/v1/runtime"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._timeout = timeout_seconds
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes

    def _post(self, path: str, payload: dict[str, object]) -> httpx.Response:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(body) > self._max_request_bytes:
            raise RuntimeGatewayError("runtime_request_too_large")
        try:
            with httpx.Client(
                timeout=self._timeout,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                with client.stream(
                    "POST",
                    self._url + path,
                    headers={**self._headers, "Content-Type": "application/json"},
                    content=body,
                ) as streamed:
                    content_length = streamed.headers.get("content-length")
                    if content_length is not None:
                        try:
                            if int(content_length) > self._max_response_bytes:
                                raise RuntimeGatewayError("runtime_response_too_large")
                        except ValueError as exc:
                            raise RuntimeGatewayError("runtime_api_invalid") from exc
                    chunks: list[bytes] = []
                    response_bytes = 0
                    for chunk in streamed.iter_bytes():
                        response_bytes += len(chunk)
                        if response_bytes > self._max_response_bytes:
                            raise RuntimeGatewayError("runtime_response_too_large")
                        chunks.append(chunk)
                    response = httpx.Response(
                        streamed.status_code,
                        headers=streamed.headers,
                        content=b"".join(chunks),
                        request=streamed.request,
                    )
        except RuntimeGatewayError:
            raise
        except httpx.HTTPError as exc:
            raise RuntimeGatewayError("runtime_api_unavailable") from exc
        if response.status_code == 401:
            raise RuntimeGatewayError("runtime_authentication_failed")
        if response.status_code == 409:
            try:
                body = response.json()
                error = body.get("error") if isinstance(body, dict) else None
                detail = error.get("code") if isinstance(error, dict) else None
            except ValueError:
                detail = None
            raise RuntimeGatewayError(detail if isinstance(detail, str) else "lease_lost")
        if response.status_code not in {200, 204}:
            raise RuntimeGatewayError("runtime_api_failed")
        return response

    @staticmethod
    def _object(response: httpx.Response) -> dict[str, object]:
        try:
            value = response.json()
        except ValueError as exc:
            raise RuntimeGatewayError("runtime_api_invalid") from exc
        if not isinstance(value, dict):
            raise RuntimeGatewayError("runtime_api_invalid")
        return cast(dict[str, object], value)

    def claim(self, *, worker_id: str) -> RuntimeClaim | None:
        response = self._post("/claims", {"worker_id": worker_id, "engine": self.engine})
        if response.status_code == 204:
            return None
        value = self._object(response)
        try:
            messages = value["messages"]
            if not isinstance(messages, list) or not all(
                isinstance(item, dict) for item in messages
            ):
                raise ValueError
            return RuntimeClaim(
                run_id=UUID(cast(str, value["run_id"])),
                lease_generation=cast(int, value["lease_generation"]),
                model_id=cast(str, value["model_id"]),
                messages=cast(list[dict[str, object]], messages),
                tool_capability=cast(str, value["tool_capability"]),
                max_output_tokens=cast(int, value["max_output_tokens"]),
                max_model_rounds=cast(int, value["max_model_rounds"]),
                max_tool_calls=cast(int, value["max_tool_calls"]),
                max_tool_argument_bytes=cast(int, value["max_tool_argument_bytes"]),
                max_tool_result_bytes=cast(int, value["max_tool_result_bytes"]),
                lease_for=timedelta(seconds=cast(int, value["lease_seconds"])),
                deadline_at=datetime.fromisoformat(str(value["deadline_at"]))
                if value.get("deadline_at")
                else None,
                runtime_spec=cast(dict[str, object] | None, value.get("runtime_spec")),
                tools=cast(list[dict[str, object]], value.get("tools", [])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeGatewayError("runtime_api_invalid") from exc

    def responses(self, claim: RuntimeClaim, worker_id: str, body: dict[str, object]) -> bytes:
        import base64

        response = self._post(
            f"/runs/{claim.run_id}/responses",
            {
                **self._lease_payload(worker_id, claim.lease_generation),
                "body": body,
            },
        )
        value = self._object(response).get("body")
        try:
            if not isinstance(value, str):
                raise ValueError
            return base64.b64decode(value, validate=True)
        except ValueError:
            raise RuntimeGatewayError("runtime_api_invalid") from None

    def _lease_payload(self, worker_id: str, lease_generation: int) -> dict[str, object]:
        return {"worker_id": worker_id, "lease_generation": lease_generation}

    def heartbeat(
        self, *, run_id: UUID, worker_id: str, lease_generation: int
    ) -> RuntimeLeaseState:
        response = self._post(
            f"/runs/{run_id}/lease", self._lease_payload(worker_id, lease_generation)
        )
        value = self._object(response)
        if value.get("active") is not True:
            raise RuntimeGatewayError("lease_lost")
        return RuntimeLeaseState(
            cancel_requested=value.get("cancel_requested") is True,
            timed_out=value.get("timed_out") is True,
        )

    def issue_model_grant(self, *, run_id: UUID, worker_id: str, lease_generation: int) -> str:
        response = self._post(
            f"/runs/{run_id}/model-grants", self._lease_payload(worker_id, lease_generation)
        )
        grant = self._object(response).get("grant")
        if not isinstance(grant, str) or not grant:
            raise RuntimeGatewayError("runtime_api_invalid")
        return grant

    def append_event(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        lease_generation: int,
        idempotency_key: str,
        kind: WorkerEventKind,
        payload: dict[str, object],
    ) -> int:
        response = self._post(
            f"/runs/{run_id}/events",
            {
                **self._lease_payload(worker_id, lease_generation),
                "idempotency_key": idempotency_key,
                "kind": kind,
                "payload": payload,
            },
        )
        cursor = self._object(response).get("cursor")
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 1:
            raise RuntimeGatewayError("runtime_api_invalid")
        return cursor

    def record_usage(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        lease_generation: int,
        idempotency_key: str,
        frame: ModelStreamFrame,
    ) -> None:
        if frame.usage is None:
            raise ValueError("usage frame required")
        self._post(
            f"/runs/{run_id}/usage",
            {
                **self._lease_payload(worker_id, lease_generation),
                "idempotency_key": idempotency_key,
                "input_tokens": frame.usage.prompt_tokens,
                "output_tokens": frame.usage.completion_tokens,
                "total_tokens": frame.usage.total_tokens,
            },
        )

    def finish(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        lease_generation: int,
        status: WorkerTerminalStatus,
        failure_code: str | None,
        final_message_md: str | None = None,
    ) -> None:
        self._post(
            f"/runs/{run_id}/finish",
            {
                **self._lease_payload(worker_id, lease_generation),
                "status": status,
                "failure_code": failure_code,
                "final_message_md": final_message_md,
            },
        )


class _RemoteLeaseHeartbeat:
    def __init__(self, gateway: RuntimeGateway, claim: RuntimeClaim, worker_id: str) -> None:
        self._gateway = gateway
        self._claim = claim
        self._worker_id = worker_id
        self._stop = threading.Event()
        self.lost = False
        self.cancel_requested = False
        self.timed_out = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self._claim.lease_for.total_seconds())

    def _run(self) -> None:
        interval = max(0.1, self._claim.lease_for.total_seconds() / 3)
        while not self._stop.wait(interval):
            try:
                state = self._gateway.heartbeat(
                    run_id=self._claim.run_id,
                    worker_id=self._worker_id,
                    lease_generation=self._claim.lease_generation,
                )
            except RuntimeGatewayError:
                self.lost = True
                return
            self.cancel_requested = state.cancel_requested
            self.timed_out = state.timed_out
            if self.cancel_requested or self.timed_out:
                return


class ApiBackedWorker:
    """Finite agent loop with no database client or canonical-state access."""

    def __init__(
        self,
        *,
        worker_id: str,
        runtime_gateway: RuntimeGateway,
        model_gateway: ModelGateway,
        tool_gateway: ToolGateway,
    ) -> None:
        if not worker_id:
            raise ValueError("worker_id is required")
        self._worker_id = worker_id
        self._runtime = runtime_gateway
        self._model = model_gateway
        self._tools = tool_gateway

    def run_once(self) -> bool:
        claim = self._runtime.claim(worker_id=self._worker_id)
        if claim is None:
            return False
        self._execute(claim)
        return True

    def _finish(
        self,
        claim: RuntimeClaim,
        status: WorkerTerminalStatus,
        failure_code: str | None,
        final_message_md: str | None = None,
    ) -> None:
        try:
            self._runtime.finish(
                run_id=claim.run_id,
                worker_id=self._worker_id,
                lease_generation=claim.lease_generation,
                status=status,
                failure_code=failure_code,
                final_message_md=final_message_md,
            )
        except RuntimeGatewayError:
            return

    def _checkpoint(self, claim: RuntimeClaim) -> bool:
        try:
            state = self._runtime.heartbeat(
                run_id=claim.run_id,
                worker_id=self._worker_id,
                lease_generation=claim.lease_generation,
            )
        except RuntimeGatewayError:
            return False
        if state.timed_out:
            self._finish(claim, "TIMED_OUT", "deadline_exceeded")
            return False
        if state.cancel_requested:
            self._finish(claim, "CANCELLED", None)
            return False
        return True

    def _execute(self, claim: RuntimeClaim) -> None:
        messages = list(claim.messages)
        completed_text: list[str] = []
        total_calls = 0
        try:
            for round_number in range(1, claim.max_model_rounds + 1):
                if not self._checkpoint(claim):
                    return
                try:
                    grant = self._runtime.issue_model_grant(
                        run_id=claim.run_id,
                        worker_id=self._worker_id,
                        lease_generation=claim.lease_generation,
                    )
                except RuntimeGatewayError as exc:
                    if exc.code != "lease_lost":
                        self._finish(claim, "FAILED", exc.code)
                    return
                result = self._model_round(claim, messages, grant, round_number)
                if result is None:
                    return
                text, calls = result
                completed_text.append(text)
                if not calls:
                    final = "".join(completed_text)
                    if final:
                        self._finish(claim, "COMPLETED", None, final)
                    else:
                        self._finish(claim, "FAILED", "model_empty_completion")
                    return
                total_calls += len(calls)
                if total_calls > claim.max_tool_calls:
                    self._finish(claim, "FAILED", "tool_call_limit_exceeded")
                    return
                messages.append(
                    {
                        "role": "assistant",
                        "content": text or None,
                        "tool_calls": [
                            {
                                "id": f"polycolab-{round_number}-{call.index}",
                                "type": "function",
                                "function": {"name": call.name, "arguments": call.arguments},
                            }
                            for call in calls
                        ],
                    }
                )
                for call in calls:
                    invocation = f"tool-{claim.run_id}-{round_number}-{call.index}"
                    try:
                        cursor = self._runtime.append_event(
                            run_id=claim.run_id,
                            worker_id=self._worker_id,
                            lease_generation=claim.lease_generation,
                            idempotency_key=invocation + "-requested",
                            kind="TOOL_REQUESTED",
                            payload={"tool_name": call.name, "round": round_number},
                        )
                        arguments = json.loads(call.arguments)
                        if not isinstance(arguments, dict):
                            raise ValueError
                        response = self._tools.call(
                            capability=claim.tool_capability,
                            name=call.name,
                            arguments=cast(dict[str, object], arguments),
                            invocation=invocation,
                            source_event_cursor=(
                                cursor
                                if call.name
                                in {
                                    "submit_proposal",
                                    "write_object_version",
                                    "create_relation",
                                    "write_summary",
                                    "comment_on_object_version",
                                    "report_progress",
                                    "submit_verification",
                                    "cancel_verification",
                                }
                                else None
                            ),
                        )
                        encoded = json.dumps(response, separators=(",", ":"), ensure_ascii=False)
                        if len(encoded.encode()) > claim.max_tool_result_bytes:
                            raise ToolGatewayError("tool_result_limit_exceeded")
                        tool_content, outcome = encoded, "ok"
                    except ValueError, json.JSONDecodeError:
                        tool_content, outcome = '{"error":"invalid_arguments"}', "invalid_arguments"
                    except ToolGatewayError as exc:
                        tool_content, outcome = json.dumps({"error": exc.code}), exc.code
                    self._runtime.append_event(
                        run_id=claim.run_id,
                        worker_id=self._worker_id,
                        lease_generation=claim.lease_generation,
                        idempotency_key=invocation + "-result",
                        kind="TOOL_RESULT",
                        payload={"tool_name": call.name, "round": round_number, "outcome": outcome},
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": f"polycolab-{round_number}-{call.index}",
                            "content": tool_content,
                        }
                    )
            self._finish(claim, "FAILED", "tool_round_limit_exceeded")
        except RuntimeGatewayError:
            return
        except Exception:
            self._finish(claim, "FAILED", "runtime_failed")

    def _model_round(
        self, claim: RuntimeClaim, messages: list[dict[str, object]], grant: str, round_number: int
    ) -> tuple[str, list[ToolCall]] | None:
        text: list[str] = []
        calls: dict[int, list[str | None]] = {}
        saw_finish = saw_usage = False
        finish_reason: str | None = None
        frame_number = 0
        stream = self._model.stream(
            ModelTurn(
                run_id=claim.run_id,
                model_id=claim.model_id,
                messages=messages,
                max_output_tokens=claim.max_output_tokens,
            ),
            grant=grant,
        )
        heartbeat = _RemoteLeaseHeartbeat(self._runtime, claim, self._worker_id)
        heartbeat.start()
        try:
            for frame in stream:
                if not self._checkpoint(claim):
                    return None
                if heartbeat.lost:
                    return None
                if heartbeat.timed_out:
                    self._finish(claim, "TIMED_OUT", "deadline_exceeded")
                    return None
                if heartbeat.cancel_requested:
                    self._finish(claim, "CANCELLED", None)
                    return None
                frame_number += 1
                if frame.content:
                    text.append(frame.content)
                    self._runtime.append_event(
                        run_id=claim.run_id,
                        worker_id=self._worker_id,
                        lease_generation=claim.lease_generation,
                        idempotency_key="model-delta-"
                        f"{claim.lease_generation}-{round_number * 10000 + frame_number}",
                        kind="ASSISTANT_DELTA",
                        payload={"text": frame.content},
                    )
                for delta in frame.tool_call_deltas:
                    state = calls.setdefault(delta.index, [None, ""])
                    if delta.name is not None:
                        if state[0] is not None and state[0] != delta.name:
                            raise ModelGatewayError("model_gateway_stream_invalid")
                        state[0] = delta.name
                    if delta.arguments is not None:
                        state[1] = str(state[1]) + delta.arguments
                        if len(str(state[1]).encode()) > claim.max_tool_argument_bytes:
                            raise ModelGatewayError("tool_argument_limit_exceeded")
                if frame.usage is not None:
                    saw_usage = True
                    self._runtime.record_usage(
                        run_id=claim.run_id,
                        worker_id=self._worker_id,
                        lease_generation=claim.lease_generation,
                        idempotency_key=(
                            f"usage-{claim.lease_generation}-{round_number * 10000 + frame_number}"
                        ),
                        frame=frame,
                    )
                if frame.finish_reason == "length":
                    self._finish(claim, "FAILED", "output_limit_reached")
                    return None
                if frame.finish_reason is not None:
                    saw_finish = True
                    finish_reason = frame.finish_reason
            if not saw_finish or not saw_usage:
                self._finish(claim, "FAILED", "model_stream_incomplete")
                return None
            if (finish_reason == "tool_calls") != bool(calls):
                self._finish(claim, "FAILED", "tool_call_invalid")
                return None
            assembled = [
                ToolCall(index=index, name=state[0], arguments=state[1])
                for index, state in sorted(calls.items())
                if state[0] is not None and state[1] is not None
            ]
            if len(assembled) != len(calls):
                self._finish(claim, "FAILED", "tool_call_invalid")
                return None
            return "".join(text), assembled
        except ModelGatewayError as exc:
            self._finish(claim, "FAILED", exc.code)
            return None
        except RuntimeGatewayError:
            return None
        except Exception:
            self._finish(claim, "FAILED", "model_gateway_failed")
            return None
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
            heartbeat.close()
