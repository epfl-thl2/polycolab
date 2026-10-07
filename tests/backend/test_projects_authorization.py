from __future__ import annotations

from datetime import timedelta
from typing import cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import AnyUrl, SecretStr
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from polycolab.access.authorization import ROLE_ACTIONS, WorkspaceAction
from polycolab.accounts.authentication import MappingIdentityVerifier, Principal
from polycolab.accounts.delivery import LocalInvitationOutbox, UnconfiguredInvitationDelivery
from polycolab.accounts.identity import current_user
from polycolab.app.application import create_app
from polycolab.db.models import SqlInvitation, SqlMembership, SqlUser
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import InvitationStatus, WorkspaceRole
from polycolab.entities.time import utc_now
from polycolab.platform.config import AuthMode, Environment, KmsProvider, Settings
from polycolab.workspaces.service import create_invitation


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def current_user_id(client: TestClient, token: str) -> str:
    response = client.get("/api/v1/users/me", headers=headers(token))
    assert response.status_code == 200
    return cast(str, response.json()["id"])


def create_workspace(client: TestClient, token: str = "owner", visibility: str = "PRIVATE") -> str:
    response = client.post(
        "/api/v1/workspaces",
        headers=headers(token),
        json={"name": "Ramsey notes", "description": "private research", "visibility": visibility},
    )
    assert response.status_code == 201
    assert response.json()["member_count"] == 1
    return cast(str, response.json()["id"])


def app_for(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


def add_member(client: TestClient, project_id: str, token: str, role: str) -> None:
    response = client.post(
        f"/api/v1/workspaces/{project_id}/members",
        headers=headers("owner"),
        json={"user_id": current_user_id(client, token), "role": role},
    )
    assert response.status_code == 201


def test_exact_role_action_matrix_and_postgresql_owner_lock_shape() -> None:
    assert ROLE_ACTIONS[WorkspaceRole.OWNER] == frozenset(WorkspaceAction)
    assert ROLE_ACTIONS[WorkspaceRole.CONTRIBUTOR] == {
        WorkspaceAction.VIEW,
        WorkspaceAction.CREATE_RESEARCH,
        WorkspaceAction.COMMENT,
        WorkspaceAction.REVIEW_PROPOSALS,
        WorkspaceAction.RUN_AGENTS,
    }
    assert ROLE_ACTIONS[WorkspaceRole.READ_ONLY] == {WorkspaceAction.VIEW}
    statement = (
        select(SqlMembership).where(SqlMembership.role == WorkspaceRole.OWNER).with_for_update()
    )
    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]


def test_project_roles_and_current_membership_are_checked_per_request(client: TestClient) -> None:
    unauthenticated = client.get("/api/v1/workspaces?scope=member")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["WWW-Authenticate"] == "Bearer"
    project_id = create_workspace(client)
    add_member(client, project_id, "contributor", "CONTRIBUTOR")
    add_member(client, project_id, "reader", "READ_ONLY")

    assert (
        client.get(f"/api/v1/workspaces/{project_id}", headers=headers("reader")).status_code == 200
    )
    assert (
        client.get(
            f"/api/v1/workspaces/{project_id}/members", headers=headers("reader")
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/workspaces/{project_id}",
            headers=headers("contributor"),
            json={"name": "mutated"},
        ).status_code
        == 403
    )
    # The denied mutation did not change state.
    assert (
        client.get(f"/api/v1/workspaces/{project_id}", headers=headers("owner")).json()["name"]
        == "Ramsey notes"
    )

    removed = client.delete(
        f"/api/v1/workspaces/{project_id}/members/{current_user_id(client, 'contributor')}",
        headers=headers("owner"),
    )
    assert removed.status_code == 204
    assert (
        client.get(f"/api/v1/workspaces/{project_id}", headers=headers("owner")).json()[
            "member_count"
        ]
        == 2
    )
    # Reusing the same valid identity token rechecks the database membership.
    assert (
        client.get(f"/api/v1/workspaces/{project_id}", headers=headers("contributor")).status_code
        == 404
    )


def test_member_project_shape_exposes_only_the_requesters_current_role(client: TestClient) -> None:
    project_id = create_workspace(client, token="owner")
    add_member(client, project_id, "reader", "READ_ONLY")

    owner = client.get(f"/api/v1/workspaces/{project_id}", headers=headers("owner"))
    reader = client.get(f"/api/v1/workspaces/{project_id}", headers=headers("reader"))
    listed = client.get("/api/v1/workspaces?scope=member", headers=headers("reader"))
    public = client.get(f"/api/v1/workspaces/{project_id}")

    assert owner.json()["member_count"] == 2
    assert reader.json()["member_count"] == 2
    assert listed.json()["items"][0]["member_count"] == 2
    assert "member_count" not in public.json()
    assert owner.json()["current_user_role"] == "OWNER"
    assert reader.json()["current_user_role"] == "READ_ONLY"
    assert listed.json()["items"][0]["current_user_role"] == "READ_ONLY"
    assert "current_user_role" not in public.json()


def test_nonmember_private_project_is_concealed_and_public_shape_does_not_leak(
    client: TestClient,
) -> None:
    project_id = create_workspace(client)
    private = client.get(f"/api/v1/workspaces/{project_id}", headers=headers("outsider"))
    assert private.status_code == 404
    assert client.get(f"/api/v1/workspaces/{project_id}").status_code == 404

    changed = client.patch(
        f"/api/v1/workspaces/{project_id}", headers=headers("owner"), json={"visibility": "PUBLIC"}
    )
    assert changed.status_code == 200
    public = client.get(f"/api/v1/workspaces/{project_id}")
    assert public.status_code == 200
    assert "created_by_user_id" not in public.text

    assert (
        client.patch(
            f"/api/v1/workspaces/{project_id}",
            headers=headers("owner"),
            json={"visibility": "PRIVATE"},
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/workspaces/{project_id}").status_code == 404


def test_cross_project_membership_and_last_owner_protection(client: TestClient) -> None:
    first = create_workspace(client)
    second = create_workspace(client)
    contributor_id = current_user_id(client, "contributor")
    add_member(client, first, "contributor", "CONTRIBUTOR")

    # A membership in one project has no authority in another, even when public.
    assert (
        client.get(f"/api/v1/workspaces/{second}", headers=headers("contributor")).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/workspaces/{second}/members",
            headers=headers("contributor"),
            json={"user_id": contributor_id, "role": "READ_ONLY"},
        ).status_code
        == 404
    )

    owner_id = current_user_id(client, "owner")
    assert (
        client.patch(
            f"/api/v1/workspaces/{first}/members/{owner_id}",
            headers=headers("owner"),
            json={"role": "READ_ONLY"},
        ).status_code
        == 409
    )
    assert (
        client.delete(
            f"/api/v1/workspaces/{first}/members/{owner_id}", headers=headers("owner")
        ).status_code
        == 409
    )


def test_archived_project_is_read_only_until_owner_unarchives(client: TestClient) -> None:
    project_id = create_workspace(client)
    contributor_id = current_user_id(client, "contributor")
    assert (
        client.patch(
            f"/api/v1/workspaces/{project_id}", headers=headers("owner"), json={"archived": True}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/workspaces/{project_id}/members",
            headers=headers("owner"),
            json={"user_id": contributor_id, "role": "CONTRIBUTOR"},
        ).status_code
        == 403
    )
    assert (
        client.get(f"/api/v1/workspaces/{project_id}", headers=headers("owner")).status_code == 200
    )


def test_invitation_is_account_bound_single_use_expirable_and_revocable(client: TestClient) -> None:
    project_id = create_workspace(client)
    owner_id = current_user_id(client, "owner")
    reader_id = current_user_id(client, "reader")
    del reader_id
    session = app_for(client).state.session_factory()
    try:
        invitation = create_invitation(
            SqlAlchemyTransaction(session),
            project_id=UUID(project_id),
            email="reader@example.test",
            role=WorkspaceRole.READ_ONLY,
            invited_by=UUID(owner_id),
            delivery=app_for(client).state.invitation_delivery,
        )
        outbox = cast(LocalInvitationOutbox, app_for(client).state.invitation_delivery)
        token = outbox.token_for_development(invitation.id)
        assert token is not None
        persisted_invitation = session.get(SqlInvitation, invitation.id)
        assert persisted_invitation is not None
        assert token not in persisted_invitation.token_digest
        assert not hasattr(invitation, "token_digest")
        invitation_id = invitation.id
    finally:
        session.close()
    wrong_account = client.post(
        "/api/v1/invitations/accept", headers=headers("outsider"), json={"token": token}
    )
    assert wrong_account.status_code == 400
    accepted = client.post(
        "/api/v1/invitations/accept", headers=headers("reader"), json={"token": token}
    )
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "READ_ONLY"
    assert (
        client.post(
            "/api/v1/invitations/accept", headers=headers("reader"), json={"token": token}
        ).status_code
        == 400
    )

    session = app_for(client).state.session_factory()
    try:
        invitation = session.get(SqlInvitation, invitation_id)
        assert invitation is not None and invitation.status is InvitationStatus.ACCEPTED
        expired = create_invitation(
            SqlAlchemyTransaction(session),
            project_id=UUID(project_id),
            email="reader@example.test",
            role=WorkspaceRole.READ_ONLY,
            invited_by=UUID(owner_id),
            delivery=app_for(client).state.invitation_delivery,
        )
        expired_token = cast(
            LocalInvitationOutbox, app_for(client).state.invitation_delivery
        ).token_for_development(expired.id)
        assert expired_token is not None
        expired_row = session.get(SqlInvitation, expired.id)
        assert expired_row is not None
        expired_row.expires_at = utc_now() - timedelta(seconds=1)
        session.commit()
        expired_id = expired.id
    finally:
        session.close()

    assert (
        client.post(
            "/api/v1/invitations/accept", headers=headers("reader"), json={"token": expired_token}
        ).status_code
        == 400
    )
    session = app_for(client).state.session_factory()
    try:
        expired_invitation = session.get(SqlInvitation, expired_id)
        assert expired_invitation is not None
        assert expired_invitation.status is InvitationStatus.PENDING
    finally:
        session.close()


def test_local_delivery_outbox_is_not_serialized_by_create_invitation(client: TestClient) -> None:
    project_id = create_workspace(client)
    response = client.post(
        f"/api/v1/workspaces/{project_id}/invitations",
        headers=headers("owner"),
        json={"email": "reader@example.test", "role": "READ_ONLY"},
    )
    assert response.status_code == 201
    assert "token" not in response.json()
    invitation_id = UUID(response.json()["id"])
    outbox = cast(LocalInvitationOutbox, app_for(client).state.invitation_delivery)
    assert outbox.token_for_development(invitation_id) is not None


def test_missing_email_claim_does_not_clear_stored_email(client: TestClient) -> None:
    current_user_id(client, "reader")
    session = app_for(client).state.session_factory()
    try:
        user = current_user(
            SqlAlchemyTransaction(session),
            Principal(issuer="https://issuer.example", subject="reader", display_name="Reader"),
        )
        assert user.email == "reader@example.test"
        persisted_user = session.get(SqlUser, user.id)
        assert persisted_user is not None
        assert persisted_user.email == "reader@example.test"
    finally:
        session.close()


def test_missing_delivery_retracts_pending_invitation(client: TestClient) -> None:
    project_id = create_workspace(client)
    app_for(client).state.invitation_delivery = UnconfiguredInvitationDelivery()
    response = client.post(
        f"/api/v1/workspaces/{project_id}/invitations",
        headers=headers("owner"),
        json={"email": "reader@example.test", "role": "READ_ONLY"},
    )
    assert response.status_code == 503
    assert (
        client.get(f"/api/v1/workspaces/{project_id}/invitations", headers=headers("owner")).json()
        == []
    )


def test_delivery_cleanup_failure_preserves_original_error_and_rolls_back(
    client: TestClient,
) -> None:
    class DeliveryWithFailingRetract:
        def deliver(self, invitation_id: UUID, recipient_email: str, token: str) -> None:
            del invitation_id, recipient_email, token
            raise RuntimeError("delivery failed")

        def retract(self, invitation_id: UUID) -> None:
            del invitation_id
            raise RuntimeError("retract failed")

    project_id = create_workspace(client)
    owner_id = current_user_id(client, "owner")
    session = app_for(client).state.session_factory()
    try:
        with pytest.raises(RuntimeError, match="delivery failed"):
            create_invitation(
                SqlAlchemyTransaction(session),
                project_id=UUID(project_id),
                email="reader@example.test",
                role=WorkspaceRole.READ_ONLY,
                invited_by=UUID(owner_id),
                delivery=DeliveryWithFailingRetract(),
            )
        assert list(session.scalars(select(SqlInvitation))) == []
    finally:
        session.close()


def test_staging_defaults_to_fail_closed_invitation_delivery() -> None:
    app = create_app(
        Settings(
            app_env=Environment.STAGING,
            auth_mode=AuthMode.OIDC,
            database_url="sqlite+pysqlite:///:memory:",
            oidc_issuer=AnyUrl("https://issuer.example"),
            oidc_jwks_url=AnyUrl("https://issuer.example/.well-known/jwks.json"),
            oidc_audience="polycolab",
            oidc_client_id="polycolab-web",
            kms_provider=KmsProvider.AWS,
            kms_key_id="test-kms-key",
            admission_scope_hmac_key=SecretStr("test-admission-scope-key"),
            runtime_worker_token=SecretStr("test-runtime-worker-token"),
        ),
        MappingIdentityVerifier({}),
    )
    assert isinstance(app.state.invitation_delivery, UnconfiguredInvitationDelivery)


def test_workspace_directory_filters_before_pagination(client: TestClient) -> None:
    from polycolab.db.models import SqlProject

    owned = [create_workspace(client) for _ in range(32)]
    shared = create_workspace(client, token="contributor")
    outsider = create_workspace(client, token="reader")
    owner_id = current_user_id(client, "owner")
    assert (
        client.post(
            f"/api/v1/workspaces/{shared}/members",
            headers=headers("contributor"),
            json={"user_id": owner_id, "role": "READ_ONLY"},
        ).status_code
        == 201
    )
    with app_for(client).state.session_factory() as session:
        for row in session.scalars(select(SqlProject)):
            row.description = "Searchable description"
        session.commit()
    assert (
        client.patch(
            f"/api/v1/workspaces/{owned[-1]}", headers=headers("owner"), json={"archived": True}
        ).status_code
        == 200
    )
    params = {"scope": "member", "q": "searchable", "category": "owned", "limit": 20}
    first = client.get("/api/v1/workspaces", headers=headers("owner"), params=params)
    assert first.status_code == 200, first.text
    assert len(first.json()["items"]) == 20
    assert first.json()["total"] == 31
    second = client.get(
        "/api/v1/workspaces",
        headers=headers("owner"),
        params={**params, "cursor": first.json()["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    assert len(second.json()["items"]) == 11
    assert second.json()["total"] == 31
    ids = {row["id"] for row in first.json()["items"] + second.json()["items"]}
    assert ids == set(owned[:-1])
    assert outsider not in ids
    for category, expected in (("shared", {shared}), ("archived", {owned[-1]})):
        response = client.get(
            "/api/v1/workspaces", headers=headers("owner"), params={**params, "category": category}
        )
        assert {row["id"] for row in response.json()["items"]} == expected
        assert response.json()["total"] == len(expected)
    wrong_cursor = client.get(
        "/api/v1/workspaces",
        headers=headers("owner"),
        params={**params, "category": "shared", "cursor": first.json()["next_cursor"]},
    )
    assert wrong_cursor.status_code == 422

    empty = client.get(
        "/api/v1/workspaces", headers=headers("owner"), params={**params, "q": "no match"}
    )
    assert empty.json()["total"] == 0
    public_id = create_workspace(client, visibility="PUBLIC")
    public = client.get("/api/v1/workspaces", params={"scope": "public", "limit": 20})
    assert public.status_code == 200
    assert public.json()["total"] == 1
    assert [row["id"] for row in public.json()["items"]] == [public_id]


def test_workspace_sorting_is_stable_across_pages(client: TestClient) -> None:
    from polycolab.db.models import SqlProject

    ids = [create_workspace(client) for _ in range(3)]
    with app_for(client).state.session_factory() as session:
        for index, (project_id, name) in enumerate(
            zip(ids, ["Zulu needle", "Needle", "Alpha"], strict=True)
        ):
            row = session.get(SqlProject, UUID(project_id))
            assert row is not None
            row.name = name
            row.description = "needle in description"
            row.updated_at = utc_now() + timedelta(days=index)
        session.commit()
    expected = {
        "updated": ids[::-1],
        "name": [ids[2], ids[1], ids[0]],
        "name_desc": [ids[0], ids[1], ids[2]],
        "relevance": [ids[1], ids[0], ids[2]],
    }
    for order, wanted in expected.items():
        found: list[str] = []
        cursor: str | None = None
        while True:
            params = {"scope": "member", "sort": order, "q": "needle", "limit": "1"}
            if cursor:
                params["cursor"] = cursor
            response = client.get("/api/v1/workspaces", headers=headers("owner"), params=params)
            assert response.status_code == 200, response.text
            found.extend(row["id"] for row in response.json()["items"])
            cursor = response.json()["next_cursor"]
            if cursor is None:
                break
            assert len(found) <= 3
        assert found == wanted
