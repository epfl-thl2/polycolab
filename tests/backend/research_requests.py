"""HTTP test helpers for receipt-based writes with resource hydration.

Contract tests inspect the raw receipt. Domain tests can request the saved
resource here, just as the browser adapter does after a successful mutation.
"""

from typing import Any, cast
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient


def post_research(client: TestClient, path: str, **kwargs: Any) -> httpx.Response:
    headers = dict(kwargs.pop("headers", {}))
    headers.setdefault("Idempotency-Key", str(uuid4()))
    response = client.post(path, headers=headers, **kwargs)
    if not response.is_success:
        return cast(httpx.Response, response)
    receipt = response.json()
    if "outputs" not in receipt:
        return cast(httpx.Response, response)
    outputs = receipt["outputs"]
    revision_id = next(
        (row["entity_id"] for row in outputs if row["entity_type"] == "OBJECT_VERSION"), None
    )
    object_id = next(
        (row["entity_id"] for row in outputs if row["entity_type"] == "RESEARCH_OBJECT"), None
    )
    if revision_id and not object_id:
        exact = client.get(f"/api/v1/versions/{revision_id}", headers=headers)
        assert exact.status_code == 200, exact.text
        object_id = exact.json()["object_id"]
    if object_id:
        hydrated = client.get(f"/api/v1/objects/{object_id}", headers=headers)
        assert hydrated.status_code == 200, hydrated.text
        body = hydrated.json()
    elif outputs[0]["entity_type"] == "RESEARCH_COMMENT":
        page = client.get(path, headers=headers).json()
        body = next(row for row in page["items"] if row["id"] == outputs[0]["entity_id"])
    else:
        body = {"id": outputs[0]["entity_id"]}
    return httpx.Response(
        response.status_code, json=body, headers=response.headers, request=response.request
    )
