"""Agent key secrets are encrypted and only revealable by their human owner."""

from typing import Any, cast
from uuid import UUID

from fastapi.testclient import TestClient

from polycolab.db.models import SqlExternalAgentCredential
from polycolab.model_gateway.credentials import LocalAesGcmKeyWrapper


def create_key(client: TestClient) -> dict[str, Any]:
    agent = client.post(
        "/api/v1/account/agents",
        headers={"Authorization": "Bearer owner"},
        json={"name": "Research helper"},
    )
    assert agent.status_code == 201
    response = client.post(
        "/api/v1/account/agent-keys",
        headers={"Authorization": "Bearer owner"},
        json={"name": "Research helper", "agent_id": agent.json()["id"]},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_owner_can_reveal_repeatedly_but_list_never_contains_secret(client: TestClient) -> None:
    key = create_key(client)
    assert key["secret_reveal_available"] is True
    app = cast(Any, client.app)
    with app.state.session_factory() as session:
        row = session.get(SqlExternalAgentCredential, UUID(key["id"]))
        assert row is not None
        assert row.encrypted_secret is not None
        assert key["secret"].encode() not in row.encrypted_secret
        assert row.wrapped_data_key is not None
        assert row.token_digest != key["secret"]
    for _ in range(2):
        response = client.post(
            f"/api/v1/account/agent-keys/{key['id']}/reveal",
            headers={"Authorization": "Bearer owner"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"secret": key["secret"]}
        assert "no-store" in response.headers["cache-control"]
    listed = client.get("/api/v1/account/agent-keys", headers={"Authorization": "Bearer owner"})
    assert key["secret"] not in listed.text
    assert "encrypted_secret" not in listed.text
    assert listed.json()["items"][0]["secret_reveal_available"] is True


def test_other_accounts_anonymous_and_agents_cannot_reveal(client: TestClient) -> None:
    key = create_key(client)
    path = f"/api/v1/account/agent-keys/{key['id']}/reveal"
    assert client.post(path).status_code == 401
    assert client.post(path, headers={"Authorization": "Bearer outsider"}).status_code == 404
    assert (
        client.post(path, headers={"Authorization": f"Bearer {key['secret']}"}).status_code == 401
    )


def test_legacy_and_revoked_keys_cannot_be_revealed(client: TestClient) -> None:
    key = create_key(client)
    app = cast(Any, client.app)
    with app.state.session_factory() as session:
        row = session.get(SqlExternalAgentCredential, UUID(key["id"]))
        assert row is not None
        row.encrypted_secret = None
        row.wrapped_data_key = None
        row.encryption_key_version = None
        session.commit()
    path = f"/api/v1/account/agent-keys/{key['id']}"
    assert (
        client.post(path + "/reveal", headers={"Authorization": "Bearer owner"}).status_code == 409
    )
    assert (
        client.get("/api/v1/me", headers={"Authorization": f"Bearer {key['secret']}"}).status_code
        == 200
    )
    second = create_key(client)
    path = f"/api/v1/account/agent-keys/{second['id']}"
    assert client.delete(path, headers={"Authorization": "Bearer owner"}).status_code == 204
    assert (
        client.post(path + "/reveal", headers={"Authorization": "Bearer owner"}).status_code == 409
    )


def test_wrong_encryption_key_fails_without_exposing_secret(client: TestClient) -> None:
    key = create_key(client)
    app = cast(Any, client.app)
    app.state.credential_wrapper = LocalAesGcmKeyWrapper(b"x" * 32)
    response = client.post(
        f"/api/v1/account/agent-keys/{key['id']}/reveal", headers={"Authorization": "Bearer owner"}
    )
    assert response.status_code == 503
    assert key["secret"] not in response.text


def test_persisted_wrapping_key_can_reveal_after_wrapper_recreation(client: TestClient) -> None:
    app = cast(Any, client.app)
    app.state.credential_wrapper = LocalAesGcmKeyWrapper(b"s" * 32)
    key = create_key(client)
    app.state.credential_wrapper = LocalAesGcmKeyWrapper(b"s" * 32)
    response = client.post(
        f"/api/v1/account/agent-keys/{key['id']}/reveal",
        headers={"Authorization": "Bearer owner"},
    )
    assert response.status_code == 200
    assert response.json() == {"secret": key["secret"]}
