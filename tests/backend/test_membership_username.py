from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from polycolab.accounts.builtin import bootstrap_admin, create_account
from polycolab.app.application import create_app
from polycolab.db.base import Base
from polycolab.db.models import SqlUser
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.accounts import LocalAccount as LocalAccountEntity
from polycolab.platform.config import Settings

PASSWORD = "correct horse battery staple"


@pytest.fixture
def local_client(tmp_path: Path) -> Generator[TestClient]:
    app = create_app(
        Settings(
            database_url="sqlite+pysqlite:///:memory:",
            web_dist_dir=str(tmp_path / "missing-web"),
        )
    )
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as session:
        bootstrap_admin(SqlAlchemyTransaction(session), PASSWORD)
    with TestClient(app, base_url="https://testserver") as client:
        yield client
    Base.metadata.drop_all(app.state.engine)
    app.state.engine.dispose()


def _register_without_api_use(
    client: TestClient, username: str, display_name: str
) -> LocalAccountEntity:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        account = create_account(
            SqlAlchemyTransaction(session),
            username=username,
            password=PASSWORD,
            display_name=display_name,
        )
        session.commit()
        return account


def test_owner_adds_exact_builtin_username_and_receives_readable_identity(
    local_client: TestClient,
) -> None:
    setup = local_client.post(
        "/auth/login",
        json={"username": "admin", "password": PASSWORD},
    )
    assert setup.status_code == 200
    project = local_client.post(
        "/api/v1/projects", json={"name": "Research research", "visibility": "PRIVATE"}
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    account = _register_without_api_use(local_client, "Bob.Example", "Bob Builder")
    app = cast(FastAPI, local_client.app)
    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(SqlUser).where(
                    SqlUser.issuer == "polycolab-local", SqlUser.subject == str(account.id)
                )
            )
            is None
        )

    added = local_client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"username": "  BOB.EXAMPLE  ", "role": "CONTRIBUTOR"},
    )
    assert added.status_code == 201, added.text
    assert added.json() == {
        "user_id": added.json()["user_id"],
        "username": "bob.example",
        "display_name": "Bob Builder",
        "role": "CONTRIBUTOR",
        "created_at": added.json()["created_at"],
    }

    listed = local_client.get(f"/api/v1/projects/{project_id}/members")
    assert listed.status_code == 200
    identities = {(item["username"], item["display_name"]) for item in listed.json()}
    assert identities == {
        ("admin", "Admin"),
        ("bob.example", "Bob Builder"),
    }

    duplicate = local_client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"username": "bob.example", "role": "READ_ONLY"},
    )
    assert duplicate.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"role": "CONTRIBUTOR"},
        {
            "user_id": "00000000-0000-0000-0000-000000000001",
            "username": "member.name",
            "role": "CONTRIBUTOR",
        },
    ],
)
def test_membership_target_requires_exactly_one_identifier(
    local_client: TestClient, payload: dict[str, str]
) -> None:
    local_client.post("/auth/login", json={"username": "admin", "password": PASSWORD})
    project_id = local_client.post(
        "/api/v1/projects", json={"name": "Research research", "visibility": "PRIVATE"}
    ).json()["id"]

    response = local_client.post(f"/api/v1/projects/{project_id}/members", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize("username", ["missing.user", "not valid!"])
def test_username_membership_is_exact_and_does_not_offer_directory_discovery(
    local_client: TestClient, username: str
) -> None:
    local_client.post("/auth/login", json={"username": "admin", "password": PASSWORD})
    project_id = local_client.post(
        "/api/v1/projects", json={"name": "Research research", "visibility": "PRIVATE"}
    ).json()["id"]

    response = local_client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"username": username, "role": "CONTRIBUTOR"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_member"
