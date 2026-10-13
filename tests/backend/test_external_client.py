"""Client against actual API policy with SQLite/fake storage, not live acceptance."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from test_public_external_agents import (
    create_human_claim,
    create_project,
    enable_research,
    issue,
)

from polycolab.agents.external_client import ExternalClient


@pytest.mark.parametrize("reverse_outputs", [False, True])
def test_external_example_completes_public_evidence_loop(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, reverse_outputs: bool
) -> None:
    enable_research(client, artifacts=True)
    project = create_project(client)
    claim = create_human_claim(client, project["id"], "Example input")
    credential = issue(client, project["id"])
    example = ExternalClient("http://127.0.0.1", credential["secret"])
    example.close()
    example._http = client
    original_request = example.request

    def request(*args: Any, **kwargs: Any) -> Any:
        result = original_request(*args, **kwargs)
        if reverse_outputs and isinstance(result, dict) and "outputs" in result:
            result["outputs"] = list(reversed(result["outputs"]))
        return result

    monkeypatch.setattr(example, "request", request)
    request_id = uuid4()
    result = example.scenario(
        request_id, UUID(claim["current_object_version_id"]), UUID(project["id"])
    )
    assert result["status"] == "COMPLETED"
    replay = example.scenario(
        request_id, UUID(claim["current_object_version_id"]), UUID(project["id"])
    )
    assert replay == {"artifact_id": result["artifact_id"], "status": "COMPLETED", "replayed": True}
