from typing import Any, cast
from uuid import UUID

from fastapi.testclient import TestClient
from test_public_external_agents import headers

from polycolab.accounts.builtin import AccountAlreadyExists, bootstrap_admin, create_account
from polycolab.db.transaction import SqlAlchemyTransaction


def test_oidc_username_claim_is_unique_and_does_not_replace_authentication_identity(
    client: TestClient,
) -> None:
    before = client.get("/api/v1/users/me", headers=headers()).json()
    assert before["username"] is None
    chosen = client.put(
        "/api/v1/account/username", headers=headers(), json={"username": " Ada.Example "}
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["id"] == before["id"]
    assert chosen.json()["username"] == "ada.example"
    assert client.get("/api/v1/users/me", headers=headers()).json()["username"] == "ada.example"
    assert (
        client.put(
            "/api/v1/account/username", headers=headers(), json={"username": "ADA.EXAMPLE"}
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/v1/account/username", headers=headers(), json={"username": "other-name"}
        ).status_code
        == 409
    )
    assert (
        client.put(
            "/api/v1/account/username",
            headers=headers("contributor"),
            json={"username": "Ada.Example"},
        ).status_code
        == 409
    )
    assert (
        client.put(
            "/api/v1/account/username",
            headers=headers("contributor"),
            json={"username": "bad/name"},
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/v1/account/username",
            headers=headers("contributor"),
            json={"username": "contributor", "user_id": before["id"]},
        ).status_code
        == 422
    )
    assert client.put("/api/v1/account/username", json={"username": "anonymous"}).status_code == 401
    app = cast(Any, client.app)
    with app.state.session_factory() as session:
        account = SqlAlchemyTransaction(session).accounts.user(UUID(before["id"]))
        assert account is not None
        assert account.issuer == "https://issuer.example" and account.subject == "owner"


def test_oidc_and_builtin_accounts_share_the_username_namespace(client: TestClient) -> None:
    app = cast(Any, client.app)
    with app.state.session_factory() as session:
        bootstrap_admin(SqlAlchemyTransaction(session), "admin-test-password")
    assert (
        client.put(
            "/api/v1/account/username", headers=headers(), json={"username": "ADMIN"}
        ).status_code
        == 409
    )
    assert (
        client.put(
            "/api/v1/account/username", headers=headers(), json={"username": "reserved-name"}
        ).status_code
        == 200
    )
    with app.state.session_factory() as session:
        import pytest

        with pytest.raises(AccountAlreadyExists):
            create_account(
                SqlAlchemyTransaction(session),
                username="reserved-name",
                password="test-account-password",
                display_name=None,
            )
