"""Runnable deterministic HTTP example; not a model or genuine agent demonstration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx


class ServiceError(Exception):
    def __init__(self, status: int, code: str, request_id: str = "") -> None:
        super().__init__(f"HTTP {status}: {code} request_id={request_id}")
        self.status = status
        self.code = code


class ExternalClient:
    def __init__(self, url: str, credential: str) -> None:
        parsed = urlsplit(url)
        if (
            (
                parsed.scheme != "https"
                and not (
                    parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                )
            )
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Use an HTTPS service origin (loopback HTTP is allowed for tests)")
        if not credential.startswith("pca_") or any(c.isspace() for c in credential):
            raise ValueError("A delegated pca_ credential is required")
        self._credential = credential
        self._http = httpx.Client(
            base_url=url.rstrip("/"), timeout=30, follow_redirects=False, trust_env=False
        )

    def close(self) -> None:
        self._http.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        key: str | None = None,
        raw: bool = False,
        **kwargs: Any,
    ) -> Any:
        if not path.startswith("/api/v1/"):
            raise ValueError("Only service API routes are permitted")
        if ".." in path or "?" in path or "#" in path or "%" in path:
            raise ValueError("Use fixed route paths and separate query parameters")
        headers = {"Authorization": f"Bearer {self._credential}"}
        if key:
            headers["Idempotency-Key"] = key
        if "content" in kwargs:
            headers["Content-Type"] = "application/octet-stream"
        for attempt in range(3):
            try:
                with self._http.stream(method, path, headers=headers, **kwargs) as response:
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 17 * 1024 * 1024:
                            raise ServiceError(502, "response_size_limit")
                    status = response.status_code
                if status >= 500 and attempt < 2:
                    time.sleep(0.25 * 2**attempt)
                    continue
                if status >= 300:
                    try:
                        error = json.loads(body).get("error", {})
                        code = str(error.get("code", "http_error"))
                        request_id = str(UUID(str(error.get("request_id"))))
                    except ValueError, TypeError, AttributeError:
                        code, request_id = "http_error", ""
                    # Never echo arbitrary server content or credential-bearing diagnostics.
                    if not code.replace("_", "").isalnum() or len(code) > 100:
                        code = "http_error"
                    raise ServiceError(status, code, request_id)
                return bytes(body) if raw else json.loads(body)
            except httpx.TransportError:
                if attempt == 2:
                    raise ServiceError(503, "transport_unavailable") from None
                time.sleep(0.25 * 2**attempt)
        raise ServiceError(503, "retry_exhausted")

    def scenario(
        self, request_id: UUID, input_object_version: UUID, workspace_id: UUID
    ) -> dict[str, Any]:
        self.request("GET", "/api/v1/me")
        project = str(workspace_id)
        # Bounded discovery; the caller selects the exact object version explicitly.
        self.request("GET", "/api/v1/workspaces", params={"limit": 25})
        self.request("GET", f"/api/v1/workspaces/{project}/objects", params={"limit": 25})
        self.request("GET", f"/api/v1/versions/{input_object_version}")
        replayed = True
        outputs = []
        for kind, content, relationships in (
            (
                "ATTEMPT",
                {
                    "outcome": "POTENTIAL",
                    "findings_md": "Deterministic API example; not a verified result",
                },
                [
                    {
                        "relationship_type": "TARGET",
                        "target_object_version_id": str(input_object_version),
                    }
                ],
            ),
            (
                "PROOF",
                {
                    "reported_progress": "POTENTIAL",
                },
                [
                    {
                        "relationship_type": role,
                        "target_object_version_id": str(input_object_version),
                    }
                    for role in ("ATTACHMENT", "CONCLUSION")
                ],
            ),
        ):
            result = self.request(
                "POST",
                "/api/v1/objects",
                key=f"{request_id}:{kind}",
                json={
                    "destination": {"kind": "workspace", "workspace_id": project},
                    "snapshot": {
                        "kind": kind,
                        "content": {
                            "title": f"External example {kind.lower()}",
                            "content_md": (
                                "Illustrative persisted research, not a mathematical proof."
                            ),
                            "assumptions_md": "None stated",
                            "reported_outcome": None,
                            "explanation_md": None,
                            **content,
                        },
                        "structural_relationships": relationships,
                        "change_summary": None,
                    },
                },
            )
            replayed = replayed and result["replayed"]
            outputs.append({item["entity_type"]: item["entity_id"] for item in result["outputs"]})
        object_version_id = outputs[1]["OBJECT_VERSION"]
        self.request(
            "POST",
            "/api/v1/relations",
            key=f"{request_id}:relation",
            json={
                "destination": {"kind": "workspace", "workspace_id": project},
                "direction": "UNIDIRECTIONAL",
                "source_object_version_id": object_version_id,
                "target_object_version_id": str(input_object_version),
                "relationship_type": "DEPENDS_ON",
                "description": "Exact input explored by this example",
            },
        )
        self.request(
            "POST",
            f"/api/v1/objects/{outputs[1]['RESEARCH_OBJECT']}/comments",
            key=f"{request_id}:comment",
            json={
                "object_version_id": object_version_id,
                "body_md": "This is an unverified illustrative approach.",
            },
        )
        evidence = b"Deterministic external HTTP example evidence; not verified computation.\n"
        artifact = self.request(
            "POST",
            "/api/v1/artifacts",
            key=f"{request_id}:upload",
            content=evidence,
            params={
                "workspace_id": project,
                "sha256": hashlib.sha256(evidence).hexdigest(),
                "byte_length": len(evidence),
                "media_type": "text/plain",
            },
        )
        artifact_id = str(UUID(artifact["id"]))
        self.request(
            "POST",
            "/api/v1/attachments",
            key=f"{request_id}:attach",
            json={
                "artifact_id": artifact_id,
                "object_version_id": object_version_id,
                "role": "EVIDENCE",
            },
        )
        for output in outputs:
            object_id = str(UUID(output["RESEARCH_OBJECT"]))
            self.request("GET", f"/api/v1/objects/{object_id}")
        if self.request("GET", f"/api/v1/artifacts/{artifact_id}/content", raw=True) != evidence:
            raise ServiceError(502, "download_integrity_mismatch")
        self.request("GET", "/api/v1/activity", params={"scope": "member", "workspace_id": project})
        return {"artifact_id": artifact_id, "status": "COMPLETED", "replayed": replayed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-id", type=UUID, required=True)
    parser.add_argument("--workspace-id", type=UUID)
    parser.add_argument("--input-object-version", type=UUID)
    parser.add_argument("--expect-revoked", action="store_true")
    args = parser.parse_args()
    if not args.expect_revoked and (args.input_object_version is None or args.workspace_id is None):
        parser.error(
            "--workspace-id and --input-object-version are required for the write scenario"
        )
    client = None
    try:
        client = ExternalClient(
            os.environ["POLYCOLAB_SERVICE_URL"], os.environ["POLYCOLAB_AGENT_CREDENTIAL"]
        )
        if args.expect_revoked:
            probes: tuple[tuple[str, str, dict[str, Any]], ...] = (
                ("GET", "/api/v1/me", {}),
                (
                    "POST",
                    "/api/v1/objects",
                    {
                        "json": {
                            "destination": {
                                "kind": "workspace",
                                "workspace_id": str(args.workspace_id),
                            },
                            "snapshot": {
                                "kind": "NOTE",
                                "content": {
                                    "title": "Revocation probe",
                                    "content_md": "probe",
                                    "assumptions_md": "None",
                                    "reported_outcome": None,
                                    "explanation_md": None,
                                },
                                "structural_relationships": [],
                            },
                        }
                    },
                ),
            )
            for method, path, payload in probes:
                try:
                    client.request(method, path, **payload)
                except ServiceError as error:
                    if error.status == 401:
                        continue
                    raise
                raise ServiceError(500, "revocation_not_enforced")
            print("Protected reads and writes denied (401)")
        else:
            print(
                json.dumps(
                    client.scenario(args.request_id, args.input_object_version, args.workspace_id)
                )
            )
    except (KeyError, ValueError, ServiceError) as error:
        print(
            str(error)
            if isinstance(error, ServiceError)
            else "Invalid client configuration or response"
        )
        return 1
    finally:
        if client is not None:
            client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
