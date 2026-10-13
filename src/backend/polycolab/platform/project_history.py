"""Historical wire adapter for the project cutover.

Never recursively rename values: user-authored content, names, grants, event bytes
and stored hashes are immutable. Only known protocol fields are projected here.
Receipt operation names and v1 serialization remain stable across the cutover.
"""

from typing import Any


def receipt_operation(operation: str) -> str:
    return {
        "project.copy": "workspace.copy",
        "project_record.moderate": "workspace_record.moderate",
    }.get(operation, operation)


def receipt_payload(operation: str, payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    body = dict(payload)
    if operation in {"project.copy", "workspace.copy", "reference.create"}:
        for current, historical in (
            ("project_name", "workspace_name"),
            ("project_visibility", "workspace_visibility"),
            ("create_new_project", "create_new_workspace"),
        ):
            if current in body:
                body[historical] = body.pop(current)
    if operation.startswith("direct."):
        if "destination_scope_id" in body and "payload" in body:
            body["payload"] = receipt_payload(operation, body["payload"])
        destination = body.get("destination")
        if isinstance(destination, dict) and destination.get("kind") == "project":
            body["destination"] = {
                **{k: v for k, v in destination.items() if k not in {"kind", "project_id"}},
                "kind": "workspace",
                "workspace_id": destination["project_id"],
            }
    return body


def grant_request(payload: dict[str, Any]) -> dict[str, Any]:
    # Caller verifies the original stored digest before invoking this projection.
    if payload.get("destination") == "WORKSPACE":
        return {**payload, "destination": "PROJECT"}
    return payload


def credential_right(value: str) -> str:
    return "PROJECT_WRITE" if value == "WORKSPACE_WRITE" else value
