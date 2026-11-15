"""Unified API reads migrated history and reveals only authorized descendants."""

from dataclasses import replace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from test_conversations_api import (
    add_member,
    create_connection,
    create_project,
    create_session,
    headers,
)

from polycolab.db.models import SqlConversation, SqlConversationItem
from polycolab.db.models.conversations import SqlLegacyConversationExecution
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.conversation import ConversationHierarchy, ConversationSharing
from polycolab.entities.enums import AgentMessageRole
from polycolab.entities.time import utc_now


@pytest.mark.parametrize("failure_code", ["chat_request_interrupted", "private diagnostic /token"])
def test_legacy_history_is_accessible_without_enabling_execution(
    client: TestClient, failure_code: str
) -> None:
    owner_id = UUID(client.get("/api/v1/account", headers=headers("owner")).json()["id"])
    provider_connection_id = UUID(str(create_connection(client, "owner")["id"]))
    conversation_id, run_id = uuid4(), uuid4()
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        db.add(
            SqlConversation(
                id=conversation_id,
                root_id=conversation_id,
                project_id=None,
                created_by_user_id=owner_id,
                title="Old investigation",
                origin="legacy_direct",
                sharing="private",
            )
        )
        db.flush()
        db.add(
            SqlLegacyConversationExecution(
                id=run_id,
                conversation_id=conversation_id,
                request_id=uuid4(),
                sequence=1,
                provider_connection_id=provider_connection_id,
                model_id="historical-model",
                status="interrupted",
                failure_code=failure_code,
                reserved_tokens=1000,
                reserved_cost_microusd=2000,
                input_tokens=None,
                output_tokens=None,
                created_at=utc_now(),
            )
        )
        db.add(
            SqlConversationItem(
                conversation_id=conversation_id,
                sequence=1,
                role=AgentMessageRole.USER,
                author_user_id=owner_id,
                content_md="Original private request",
                execution_id=run_id,
                status="interrupted",
                item_type="message",
                visibility="user_visible",
            )
        )
        db.add(
            SqlConversationItem(
                conversation_id=conversation_id,
                sequence=2,
                role=AgentMessageRole.SYSTEM,
                content_md="",
                execution_id=run_id,
                status="interrupted",
                item_type="error",
                payload={"code": failure_code},
                visibility="user_visible",
            )
        )
        db.commit()
    root = f"/api/v1/conversations/{conversation_id}"
    value = client.get(root, headers=headers("owner")).json()
    assert value["project_id"] is None and value["origin"] == "legacy_direct"
    assert value["configuration"] is None
    assert value["capabilities"] == {
        "can_send": False,
        "can_manage": True,
        "can_share": False,
        "can_stream": False,
    }
    assert value["latest_execution"]["status"] == "INTERRUPTED"
    expected_code = (
        "chat_request_interrupted"
        if failure_code == "chat_request_interrupted"
        else "execution_failed"
    )
    assert value["latest_execution"]["failure_code"] == expected_code
    listing = client.get(
        "/api/v1/conversations", params={"origin": "legacy_direct"}, headers=headers("owner")
    )
    assert [entry["id"] for entry in listing.json()] == [str(conversation_id)]
    items = client.get(root + "/items", headers=headers("owner")).json()["items"]
    assert items[0]["data"]["content_md"] == "Original private request"
    assert items[0]["status"] == "interrupted"
    assert items[1]["data"] == {"code": expected_code}
    run = client.get(f"/api/v1/runs/{run_id}", headers=headers("owner")).json()
    assert run["requested_model"] == "historical-model" and run["observed_model"] is None
    assert run["failure_code"] == expected_code
    assert run["usage"]["observations"][0]["input_tokens"] is None
    assert run["usage"]["reservations"][0]["tokens"] == 1000
    assert not run["can_resume"] and not run["can_interrupt"]
    for path in (root, root + "/items", root + "/runs", f"/api/v1/runs/{run_id}"):
        assert client.get(path, headers=headers("contributor")).status_code == 404
    for payload in (
        {
            "type": "message",
            "client_request_id": str(uuid4()),
            "content_md": "Continue",
            "provider_connection_id": str(provider_connection_id),
        },
        {"type": "interrupt", "run_id": str(run_id)},
    ):
        assert (
            client.post(root + "/events", headers=headers("owner"), json=payload).status_code == 409
        )
    assert (
        client.post(
            f"/api/v1/runs/{run_id}/resume",
            headers=headers("owner"),
            json={
                "client_request_id": str(uuid4()),
                "provider_connection_id": str(provider_connection_id),
            },
        ).status_code
        == 409
    )
    assert (
        client.patch(
            root + "/sharing",
            headers=headers("owner"),
            json={"mode": "members_can_view"},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            root, headers=headers("owner"), json={"configuration": {"harness": "codex"}}
        ).status_code
        == 422
    )
    updated = client.patch(
        root, headers=headers("owner"), json={"title": "Retained", "archived": True}
    )
    assert updated.status_code == 200 and updated.json()["status"] == "archived"
    assert client.get(root + "/items", headers=headers("owner")).json()["items"] == items


def test_children_are_independently_authorized_and_parentage_is_not_editable(
    client: TestClient,
) -> None:
    project_id = str(create_project(client)["id"])
    add_member(client, project_id, "contributor", "EDITOR")
    root_id = UUID(str(create_session(client, project_id)["id"]))
    root_path = f"/api/v1/conversations/{root_id}"
    assert (
        client.patch(
            root_path + "/sharing",
            headers=headers("owner"),
            json={"mode": "members_can_view"},
        ).status_code
        == 200
    )
    app = cast(Any, client.app)
    hidden_id, visible_id = uuid4(), uuid4()
    with app.state.session_factory() as db:
        transaction = SqlAlchemyTransaction(db)
        parent = transaction.conversations.conversation(root_id)
        assert parent is not None
        for identity, sharing in (
            (hidden_id, ConversationSharing.PRIVATE),
            (visible_id, ConversationSharing.MEMBERS_CAN_VIEW),
        ):
            transaction.conversations.create(
                replace(
                    parent,
                    id=identity,
                    sharing=sharing,
                    hierarchy=ConversationHierarchy(root_id=root_id, parent_id=root_id),
                )
            )
        transaction.commit()
    visible = client.get(root_path + "/child_conversations", headers=headers("contributor"))
    assert visible.status_code == 200
    assert [value["id"] for value in visible.json()] == [str(visible_id)]
    assert "total" not in visible.headers and "count" not in visible.text
    assert (
        client.get(f"/api/v1/conversations/{hidden_id}", headers=headers("contributor")).status_code
        == 404
    )
    owner = client.get(root_path + "/child_conversations", headers=headers("owner"))
    assert {value["id"] for value in owner.json()} == {str(hidden_id), str(visible_id)}
    assert (
        client.patch(
            f"/api/v1/conversations/{hidden_id}",
            headers=headers("owner"),
            json={"parent_id": str(visible_id)},
        ).status_code
        == 422
    )
    assert (
        client.post(
            root_path + "/child_conversations", headers=headers("owner"), json={}
        ).status_code
        == 405
    )
