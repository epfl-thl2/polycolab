from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from research_requests import post_research
from test_catalogue_api import admit, enable, headers
from test_public_external_agents import version_snapshot
from test_research_domain import add_member, create_object, create_project


def attempt_payload(
    *,
    target_revision_id: str,
    statement_revision_id: str,
    title: str,
    outcome: str = "FAILED",
) -> dict[str, Any]:
    snapshot = version_snapshot("ATTEMPT", title, f"Activity for {title}")
    snapshot["content"].update(
        reported_outcome={
            "POTENTIAL": "IN_PROGRESS",
            "PARTIAL": "PARTIAL",
            "COMPLETE": "SUCCEEDED",
            "STALLED": "FAILED",
            "FAILED": "FAILED",
        }[outcome],
        explanation_md="The approach did not close the target",
        outcome=outcome,
        findings_md=f"Findings for {title}",
    )
    snapshot["structural_relationships"] = [
        {"relationship_type": "ATTACHMENT", "target_object_version_id": statement_revision_id},
        {"relationship_type": "TARGET", "target_object_version_id": target_revision_id},
        {
            "relationship_type": "EVIDENCE",
            "target_object_version_id": statement_revision_id,
            "position": 0,
            "evidence_role": "INPUT",
        },
    ]
    return {
        "destination": {"kind": "library", "statement_object_version_id": statement_revision_id},
        "snapshot": snapshot,
    }


def proof_snapshot(
    statement_id: str, title: str, premise_ids: list[str] | None = None
) -> dict[str, Any]:
    value = version_snapshot("PROOF_SKETCH", title, f"Argument for {title}")
    value["content"]["reported_progress"] = "COMPLETE"
    value["structural_relationships"] = [
        {"relationship_type": role, "target_object_version_id": statement_id}
        for role in ("ATTACHMENT", "CONCLUSION")
    ]
    for position, premise_id in enumerate(premise_ids or []):
        value["structural_relationships"].extend(
            [
                {"relationship_type": "ATTACHMENT", "target_object_version_id": premise_id},
                {
                    "relationship_type": "PREMISE",
                    "target_object_version_id": premise_id,
                    "position": position,
                },
            ]
        )
    return value


def saved_version(client: TestClient, receipt: Any) -> dict[str, Any]:
    version_id = next(
        item["entity_id"] for item in receipt["outputs"] if item["entity_type"] == "OBJECT_VERSION"
    )
    response = client.get(f"/api/v1/versions/{version_id}")
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def targets(version: dict[str, Any], role: str) -> list[str]:
    return [
        pin["target_object_version_id"]
        for pin in version["structural_relationships"]
        if pin["relationship_type"] == role
    ]


def test_attempt_history_is_exact_attributable_and_not_recursive(client: TestClient) -> None:
    enable(client)
    statement = admit(client, "attempt-target")
    sketch_response = client.post(
        "/api/v1/objects",
        headers=headers(key="attempt-sketch"),
        json={
            "destination": {
                "kind": "library",
                "statement_object_version_id": statement["object_version_id"],
            },
            "snapshot": proof_snapshot(statement["object_version_id"], "Attempted sketch"),
        },
    )
    assert sketch_response.status_code == 201, sketch_response.text
    sketch = saved_version(client, sketch_response.json())

    attempts = []
    for index in range(2):
        response = client.post(
            "/api/v1/objects",
            headers=headers(key=f"research-attempt-{index}"),
            json=attempt_payload(
                target_revision_id=sketch["id"],
                statement_revision_id=statement["object_version_id"],
                title=f"Attempt {index}",
            ),
        )
        assert response.status_code == 201, response.text
        attempts.append(saved_version(client, response.json()))

    history = client.get(
        f"/api/v1/research/objects/{sketch['object_id']}/attempts",
        params={"target_object_version_id": sketch["id"]},
    )
    assert history.status_code == 200, history.text
    items = history.json()["items"]
    assert {item["object_id"] for item in items} == {item["object_id"] for item in attempts}
    assert {item["content"]["outcome"] for item in items} == {"FAILED"}
    assert all(targets(item, "TARGET") == [sketch["id"]] for item in items)
    assert all(targets(item, "RESULT") == [] for item in items)
    first_page = client.get(
        f"/api/v1/research/objects/{sketch['object_id']}/attempts",
        params={"target_object_version_id": sketch["id"], "limit": 1},
    ).json()
    assert len(first_page["items"]) == 1 and first_page["next_cursor"]
    second_page = client.get(
        f"/api/v1/research/objects/{sketch['object_id']}/attempts",
        params={
            "target_object_version_id": sketch["id"],
            "limit": 1,
            "cursor": first_page["next_cursor"],
        },
    ).json()
    assert len(second_page["items"]) == 1
    assert first_page["items"] + second_page["items"] == items

    revised = client.post(
        f"/api/v1/objects/{sketch['object_id']}/versions",
        headers=headers(key="revise-attempt-sketch"),
        json={
            "expected_current_object_version_id": sketch["id"],
            "snapshot": proof_snapshot(statement["object_version_id"], "Revised attempted sketch"),
        },
    )
    assert revised.status_code == 201, revised.text
    revised_version = saved_version(client, revised.json())
    assert (
        client.get(
            f"/api/v1/research/objects/{sketch['object_id']}/attempts",
            params={"target_object_version_id": sketch["id"]},
        ).json()["items"]
        == items
    )
    assert (
        client.get(
            f"/api/v1/research/objects/{sketch['object_id']}/attempts",
            params={"target_object_version_id": revised_version["id"]},
        ).json()["items"]
        == []
    )

    completed = attempt_payload(
        target_revision_id=sketch["id"],
        statement_revision_id=statement["object_version_id"],
        title="Attempt with a resulting revision",
        outcome="COMPLETE",
    )
    completed["snapshot"]["structural_relationships"].append(
        {"relationship_type": "RESULT", "target_object_version_id": revised_version["id"]}
    )
    result_attempt = client.post(
        "/api/v1/objects",
        headers=headers(key="result-attempt"),
        json=completed,
    )
    assert result_attempt.status_code == 201, result_attempt.text
    result_record = saved_version(client, result_attempt.json())
    assert targets(result_record, "RESULT") == [revised_version["id"]]

    mismatched_result = attempt_payload(
        target_revision_id=sketch["id"],
        statement_revision_id=statement["object_version_id"],
        title="Attempt with a mismatched result",
    )
    mismatched_result["snapshot"]["structural_relationships"].append(
        {"relationship_type": "RESULT", "target_object_version_id": statement["object_version_id"]}
    )
    assert (
        client.post(
            "/api/v1/objects",
            headers=headers(key="mismatched-result"),
            json=mismatched_result,
        ).status_code
        == 409
    )

    recursive = attempt_payload(
        target_revision_id=attempts[0]["id"],
        statement_revision_id=statement["object_version_id"],
        title="Recursive attempt",
    )
    response = client.post(
        "/api/v1/objects",
        headers=headers(key="recursive-attempt"),
        json=recursive,
    )
    assert response.status_code == 409

    statement_attempt = client.post(
        "/api/v1/objects",
        headers=headers(key="statement-target-attempt"),
        json=attempt_payload(
            target_revision_id=statement["object_version_id"],
            statement_revision_id=statement["object_version_id"],
            title="Attempt against a statement",
        ),
    )
    assert statement_attempt.status_code == 201, statement_attempt.text
    statement_history = client.get(
        f"/api/v1/research/objects/{statement['entry_id']}/attempts",
        params={"target_object_version_id": statement["object_version_id"]},
    ).json()
    assert [item["object_id"] for item in statement_history["items"]] == [
        saved_version(client, statement_attempt.json())["object_id"]
    ]


@pytest.mark.parametrize(
    "target_kind",
    [
        "PROBLEM",
        "DEFINITION",
        "CLAIM",
        "PROOF_SKETCH",
        "COUNTEREXAMPLE",
        "NOTE",
        "IDEA",
        "DISCUSSION",
        "FORMALIZATION",
        "COMPUTATION",
    ],
)
def test_attempt_history_accepts_every_createable_non_attempt_kind(
    client: TestClient, target_kind: str
) -> None:
    enable(client)
    statement = admit(client, f"target-{target_kind.lower()}")
    if target_kind == "PROOF_SKETCH":
        snapshot = proof_snapshot(statement["object_version_id"], f"Target {target_kind}")
    else:
        snapshot = version_snapshot(
            target_kind, f"Target {target_kind}", "A target for independently attributable work."
        )
        snapshot["structural_relationships"] = [
            {
                "relationship_type": "ATTACHMENT",
                "target_object_version_id": statement["object_version_id"],
            }
        ]
    target_response = client.post(
        "/api/v1/objects",
        headers=headers(key=f"create-{target_kind}"),
        json={
            "destination": {
                "kind": "library",
                "statement_object_version_id": statement["object_version_id"],
            },
            "snapshot": snapshot,
        },
    )
    assert target_response.status_code == 201, target_response.text
    target = saved_version(client, target_response.json())

    attempt_response = client.post(
        "/api/v1/objects",
        headers=headers(key=f"attempt-{target_kind}"),
        json=attempt_payload(
            target_revision_id=target["id"],
            statement_revision_id=statement["object_version_id"],
            title=f"Attempt against {target_kind}",
        ),
    )
    assert attempt_response.status_code == 201, attempt_response.text
    history = client.get(
        f"/api/v1/research/objects/{target['object_id']}/attempts",
        params={"target_object_version_id": target["id"]},
    )
    assert history.status_code == 200, history.text
    assert [item["object_id"] for item in history.json()["items"]] == [
        saved_version(client, attempt_response.json())["object_id"]
    ]


def test_human_note_summary_comments_and_progress_keep_explicit_history(
    client: TestClient,
) -> None:
    enable(client)
    statement = admit(client, "associated-history")
    object_id = statement["entry_id"]
    revision_id = statement["object_version_id"]

    note = client.put(
        f"/api/v1/research/objects/{object_id}/human-note",
        headers=headers(key="human-note-one"),
        json={"body_md": "Private working note"},
    )
    assert note.status_code == 200, note.text
    note_revision = note.json()["current_revision"]
    replay = client.put(
        f"/api/v1/research/objects/{object_id}/human-note",
        headers=headers(key="human-note-one"),
        json={"body_md": "Private working note"},
    )
    assert replay.json() == note.json()
    denied = client.put(
        f"/api/v1/research/objects/{object_id}/human-note",
        headers=headers("contributor", key="steal-human-note"),
        json={
            "base_revision_id": note_revision["id"],
            "body_md": "Overwrite another human's note",
        },
    )
    assert denied.status_code == 403
    assert (
        client.get(
            f"/api/v1/research/objects/{object_id}/human-note",
            headers=headers("contributor"),
        ).status_code
        == 404
    )
    stale = client.put(
        f"/api/v1/research/objects/{object_id}/human-note",
        headers=headers(key="stale-human-note"),
        json={"body_md": "Missing exact base"},
    )
    assert stale.status_code == 409
    revised_note = client.put(
        f"/api/v1/research/objects/{object_id}/human-note",
        headers=headers(key="human-note-two"),
        json={
            "base_revision_id": note_revision["id"],
            "body_md": "Second immutable note revision",
        },
    )
    assert revised_note.status_code == 200, revised_note.text
    note_history = client.get(
        f"/api/v1/research/objects/{object_id}/human-note/history", headers=headers()
    ).json()
    assert [item["number"] for item in note_history["items"]] == [1, 2]

    summary = client.put(
        f"/api/v1/research/objects/{object_id}/summary",
        headers=headers(key="summary-one"),
        json={
            "body_md": "Source-pinned authored summary",
            "source_object_version_ids": [revision_id],
        },
    )
    assert summary.status_code == 200, summary.text
    summary_revision = summary.json()["current_revision"]
    assert summary_revision["source_object_version_ids"] == [revision_id]
    assert "source_revision_ids" not in summary_revision
    for sources in (
        {"source_revision_ids": [revision_id]},
        {"source_object_version_ids": [revision_id, revision_id]},
    ):
        invalid = client.put(
            f"/api/v1/research/objects/{object_id}/summary",
            headers=headers(key="invalid-summary"),
            json={"body_md": "Invalid source selection", **sources},
        )
        assert invalid.status_code == 422, invalid.text
    assert (
        client.put(
            f"/api/v1/research/objects/{object_id}/summary",
            headers=headers(key="summary-stale"),
            json={
                "body_md": "Stale summary",
                "source_object_version_ids": [revision_id],
            },
        ).status_code
        == 409
    )

    for index, status in enumerate(("POTENTIAL", "PARTIAL")):
        progress = client.post(
            f"/api/v1/research/objects/{object_id}/progress",
            headers=headers(key=f"progress-{index}"),
            json={
                "object_version_id": revision_id,
                "status": status,
                "detail_md": f"Progress {index}",
            },
        )
        assert progress.status_code == 201, progress.text
        comment = client.post(
            f"/api/v1/research/objects/{object_id}/comments",
            headers=headers(key=f"comment-{index}"),
            json={"object_version_id": revision_id, "body_md": f"Comment {index}"},
        )
        assert comment.status_code == 201, comment.text
        for resource, payload, response in (
            (
                "progress",
                {
                    "object_version_id": revision_id,
                    "status": status,
                    "detail_md": f"Progress {index}",
                },
                progress,
            ),
            (
                "comments",
                {"object_version_id": revision_id, "body_md": f"Comment {index}"},
                comment,
            ),
        ):
            assert response.json()["object_version_id"] == revision_id
            assert "revision_id" not in response.json()
            key = f"progress-{index}" if resource == "progress" else f"comment-{index}"
            replay = client.post(
                f"/api/v1/research/objects/{object_id}/{resource}",
                headers=headers(key=key),
                json=payload,
            )
            assert replay.status_code == 201, replay.text
            assert replay.json() == response.json()
            old = {**payload, "revision_id": payload["object_version_id"]}
            old.pop("object_version_id")
            assert (
                client.post(
                    f"/api/v1/research/objects/{object_id}/{resource}",
                    headers=headers(key="old-shape"),
                    json=old,
                ).status_code
                == 422
            )

    progress_page = client.get(
        f"/api/v1/research/objects/{object_id}/progress",
        headers=headers(),
        params={"object_version_id": revision_id, "limit": 1},
    ).json()
    assert len(progress_page["items"]) == 1
    assert progress_page["next_cursor"] is not None
    comment_page = client.get(
        f"/api/v1/research/objects/{object_id}/comments",
        headers=headers(),
        params={"object_version_id": revision_id},
    ).json()
    assert [item["body_md"] for item in comment_page["items"]] == [
        "Comment 0",
        "Comment 1",
    ]
    assert all(item["object_version_id"] == revision_id for item in comment_page["items"])


def test_private_note_capability_summary_freshness_and_batched_revision_display(
    client: TestClient,
) -> None:
    enable(client)
    project_id = create_project(client)
    source = create_object(client, project_id, title="Original source")
    object_id = source["id"]
    source_revision_id = source["current_object_version_id"]
    owner_id = client.get("/api/v1/users/me", headers=headers()).json()["id"]

    note = client.put(
        f"/api/v1/research/objects/{object_id}/human-note",
        headers=headers(key="private-note-capability"),
        json={"project_id": project_id, "body_md": "Owner-only edit stream"},
    )
    assert note.status_code == 200, note.text
    assert note.json()["owner_user_id"] == owner_id
    assert note.json()["can_edit"] is True
    add_member(client, project_id, "contributor", "CONTRIBUTOR")
    member_note = client.get(
        f"/api/v1/research/objects/{object_id}/human-note",
        headers=headers("contributor"),
        params={"project_id": project_id},
    )
    assert member_note.status_code == 200
    assert member_note.json()["owner_user_id"] == owner_id
    assert member_note.json()["can_edit"] is False
    contributor_object = create_object(client, project_id, title="Contributor note target")
    contributor_note = client.put(
        f"/api/v1/research/objects/{contributor_object['id']}/human-note",
        headers=headers("contributor", key="contributor-note-capability"),
        json={"project_id": project_id, "body_md": "Contributor-owned edit stream"},
    )
    assert contributor_note.status_code == 200
    assert contributor_note.json()["can_edit"] is True
    contributor_id = client.get("/api/v1/users/me", headers=headers("contributor")).json()["id"]
    downgraded = client.patch(
        f"/api/v1/projects/{project_id}/members/{contributor_id}",
        headers=headers(),
        json={"role": "READ_ONLY"},
    )
    assert downgraded.status_code == 200
    downgraded_note = client.get(
        f"/api/v1/research/objects/{contributor_object['id']}/human-note",
        headers=headers("contributor"),
        params={"project_id": project_id},
    )
    assert downgraded_note.status_code == 200
    assert downgraded_note.json()["can_edit"] is False
    archived = client.patch(
        f"/api/v1/projects/{project_id}",
        headers=headers(),
        json={"archived": True},
    )
    assert archived.status_code == 200
    archived_note = client.get(
        f"/api/v1/research/objects/{object_id}/human-note",
        headers=headers(),
        params={"project_id": project_id},
    )
    assert archived_note.status_code == 200
    assert archived_note.json()["can_edit"] is False
    unarchived = client.patch(
        f"/api/v1/projects/{project_id}",
        headers=headers(),
        json={"archived": False},
    )
    assert unarchived.status_code == 200

    summary = client.put(
        f"/api/v1/research/objects/{object_id}/summary",
        headers=headers(key="fresh-summary"),
        json={
            "project_id": project_id,
            "body_md": "Summary of the exact original source",
            "source_object_version_ids": [source_revision_id],
        },
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["current_revision"]["fresh"] is True
    revised = post_research(
        client,
        f"/api/v1/objects/{object_id}/versions",
        headers=headers(),
        json={
            "expected_current_object_version_id": source_revision_id,
            "snapshot": version_snapshot("CLAIM", "Revised source", "New exact content"),
        },
    )
    assert revised.status_code == 201, revised.text
    revised_id = revised.json()["current_object_version_id"]
    current_summary = client.get(
        f"/api/v1/research/objects/{object_id}/summary",
        headers=headers(),
        params={"project_id": project_id},
    )
    assert current_summary.status_code == 200
    assert current_summary.json()["current_revision"]["fresh"] is False

    display = client.post(
        "/api/v1/research/versions/display",
        headers=headers("contributor"),
        json={
            "project_id": project_id,
            "object_version_ids": [revised_id, source_revision_id],
        },
    )
    assert display.status_code == 200, display.text
    assert [item["title"] for item in display.json()["items"]] == [
        "Revised source",
        "Original source",
    ]
    assert (
        client.post(
            "/api/v1/research/versions/display",
            headers=headers("outsider"),
            json={"project_id": project_id, "object_version_ids": [source_revision_id]},
        ).status_code
        == 404
    )
