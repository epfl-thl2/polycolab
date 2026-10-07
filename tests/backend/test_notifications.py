"""Bounded delivery survives retries and cached summaries obey current visibility."""

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, select
from test_catalogue_api import admit, enable, headers
from test_library_api import attempt_payload

from polycolab.db.models import (
    SqlCommunityDeliveryCursor,
    SqlMembership,
    SqlObjectRevision,
    SqlRecordModeration,
    SqlResearchNotification,
)
from polycolab.research.notifications import process_one, read_summary


def drain(app: Any) -> None:
    with app.state.session_factory() as db:
        for _ in range(100):
            if not process_one(db, recipient_limit=1):
                return
    raise AssertionError("consumer did not finish its bounded fan-out")


def test_notification_retry_reference_revocation_and_filtered_summary(client: TestClient) -> None:
    app = enable(client)
    entry = admit(client)
    client.put(
        f"/api/v1/community/{entry['entry_id']}/follow", headers=headers(), json={"active": True}
    )
    reference = client.post(
        "/api/v1/workspace-references",
        headers=headers("outsider", "ref"),
        json={"object_version_id": entry["object_version_id"]},
    ).json()
    payload = attempt_payload(entry["object_version_id"])
    payload["snapshot"]["content"].update(
        reported_outcome="FAILED", explanation_md="A stronger hypothesis is needed"
    )
    response = client.post("/api/v1/objects", headers=headers(key="record"), json=payload)
    assert response.status_code == 201
    outputs = {item["entity_type"]: item["entity_id"] for item in response.json()["outputs"]}
    record_version_id = outputs["OBJECT_VERSION"]
    record_object_id = outputs["RESEARCH_OBJECT"]
    drain(app)
    owner = client.get("/api/v1/notifications", headers=headers()).json()
    other = client.get("/api/v1/notifications", headers=headers("outsider")).json()
    assert record_version_id in {value["object_version_id"] for value in owner["items"]}
    assert record_version_id in {value["object_version_id"] for value in other["items"]}
    summary = client.get(f"/api/v1/community/{entry['entry_id']}/summary").json()
    assert summary["state"] == "READY"
    assert summary["status_counts"] == {"FAILED": 1}
    assert summary["items"][0]["object_version_id"] == record_version_id
    assert all("revision_id" not in value for value in owner["items"] + summary["items"])
    with app.state.session_factory() as db:
        count = db.scalar(select(func.count()).select_from(SqlResearchNotification))
        # Derived consumer cursors may be rebuilt without duplicating notifications.
        db.execute(delete(SqlCommunityDeliveryCursor))
        db.commit()
    drain(app)
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(SqlResearchNotification)) == count
        db.execute(
            delete(SqlMembership).where(SqlMembership.project_id == UUID(reference["workspace_id"]))
        )
        db.add(SqlRecordModeration(object_id=UUID(record_object_id), hidden=True))
        db.commit()
    assert client.get("/api/v1/notifications", headers=headers("outsider")).json()["items"] == []
    visible = client.get("/api/v1/notifications", headers=headers()).json()["items"]
    assert record_version_id not in {value["object_version_id"] for value in visible}
    filtered = client.get(f"/api/v1/community/{entry['entry_id']}/summary").json()
    assert filtered["items"] == [] and filtered["status_counts"] == {}


@pytest.mark.parametrize("kind", ["STATEMENT", "DEFINITION", "PROBLEM"])
def test_summary_includes_statement_outcomes_without_per_item_queries(
    client: TestClient, kind: str
) -> None:
    app = enable(client)
    entry = admit(client)
    revision_ids: set[str] = set()
    for record_kind in ("ATTEMPT", kind):
        payload = attempt_payload(entry["object_version_id"])
        snapshot = payload["snapshot"]
        snapshot["kind"] = record_kind
        snapshot["content"].update(
            reported_outcome="FAILED", explanation_md="A stronger hypothesis is needed"
        )
        if record_kind != "ATTEMPT":
            snapshot["content"].pop("outcome")
            snapshot["content"].pop("findings_md")
            snapshot["structural_relationships"] = [
                pin
                for pin in snapshot["structural_relationships"]
                if pin["relationship_type"] == "ATTACHMENT"
            ]
        response = client.post("/api/v1/objects", headers=headers(key=record_kind), json=payload)
        assert response.status_code == 201, response.text
        revision_ids.update(
            item["entity_id"]
            for item in response.json()["outputs"]
            if item["entity_type"] == "OBJECT_VERSION"
        )
    drain(app)
    statements: list[str] = []

    def capture(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    with app.state.session_factory() as db:
        connection = db.connection()
        event.listen(connection, "before_cursor_execute", capture)
        try:
            summary = read_summary(db, UUID(entry["entry_id"]))
        finally:
            event.remove(connection, "before_cursor_execute", capture)
    assert summary["status_counts"] == {"FAILED": 2}
    items = summary["items"]
    assert isinstance(items, list)
    assert {item["object_version_id"] for item in items} == revision_ids
    assert all(item["reported_outcome"] == "FAILED" for item in items)
    assert sum("record_revisions" in statement for statement in statements) == 1


def test_progress_summary_uses_the_exact_released_content(client: TestClient) -> None:
    app = enable(client)
    entry = admit(client)
    response = client.post(
        "/api/v1/objects",
        headers=headers(key="released-attempt"),
        json=attempt_payload(entry["object_version_id"]),
    )
    assert response.status_code == 201, response.text
    version_id = next(
        output["entity_id"]
        for output in response.json()["outputs"]
        if output["entity_type"] == "OBJECT_VERSION"
    )
    exact = client.get(f"/api/v1/versions/{version_id}").json()
    drain(app)
    with app.state.session_factory() as db:
        # SQLite fixture deliberately separates raw and released content. This
        # is a projection regression, not an authorized mutation of immutable rows.
        raw = db.get(SqlObjectRevision, UUID(version_id))
        assert raw is not None
        raw.title = "Unreleased raw title"
        raw.content_md = "Unreleased raw content"
        db.commit()
    summary = client.get(f"/api/v1/community/{entry['entry_id']}/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["items"] == [
        {
            "object_version_id": version_id,
            "title": exact["content"]["title"],
            "excerpt": exact["content"]["content_md"][:300],
            "reported_outcome": exact["content"]["reported_outcome"],
        }
    ]
    assert "Unreleased raw" not in summary.text
