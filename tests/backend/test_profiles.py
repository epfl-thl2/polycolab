from typing import Any, cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from research_requests import post_research
from sqlalchemy import select
from test_public_external_agents import enable_research, headers, issue, version_snapshot

from polycolab.db.models import SqlResearchActivityEvent


def project(client: TestClient, token: str, visibility: str = "PUBLIC") -> str:
    response = client.post(
        "/api/v1/projects",
        headers=headers(token),
        json={"name": f"Research by {token}", "visibility": visibility},
    )
    assert response.status_code == 201, response.text
    chosen = client.put(
        "/api/v1/account/username", headers=headers(token), json={"username": token}
    )
    assert chosen.status_code == 200, chosen.text
    return str(response.json()["id"])


def contribute(client: TestClient, project_id: str, token: str) -> None:
    response = post_research(
        client,
        "/api/v1/objects",
        headers=headers(token),
        json={
            "destination": {"kind": "project", "project_id": project_id},
            "snapshot": version_snapshot("CLAIM", "A public claim", "Research"),
        },
    )
    assert response.status_code == 201, response.text


def test_profile_counts_public_authorship_and_sponsorship_only(client: TestClient) -> None:
    enable_research(client)
    public = project(client, "owner")
    contribute(client, public, "owner")
    sponsored_project = project(client, "contributor")
    credential = issue(client, sponsored_project, "contributor")
    contribute(client, sponsored_project, credential["secret"])
    contribute(client, project(client, "reader", "PRIVATE"), "reader")
    empty_id = client.get("/api/v1/me", headers=headers("outsider")).json()["user_id"]
    owner_id = UUID(client.get("/api/v1/me", headers=headers()).json()["user_id"])
    app = cast(Any, client.app)
    with app.state.session_factory() as session:
        # Several history events from one contribution must count once.
        original = session.scalar(
            select(SqlResearchActivityEvent).where(
                SqlResearchActivityEvent.actor_user_id == owner_id
            )
        )
        assert original is not None
        session.add(
            SqlResearchActivityEvent(
                source_kind="ResearchProgressUpdate",
                source_id=uuid4(),
                contribution_id=original.contribution_id,
                actor_user_id=original.actor_user_id,
                ownership_scope_id=original.ownership_scope_id,
                object_id=original.object_id,
                revision_id=original.revision_id,
                action="progress.reported",
            )
        )
        session.commit()

    response = client.get("/api/v1/profile/owner")
    assert response.status_code == 200, response.text
    rows = [client.get("/api/v1/profile/contributor").json(), response.json()]
    assert [row["actor"]["display_name"] for row in rows] == ["Contributor", "Owner"]
    assert [(row["authored_contributions"], row["sponsored_contributions"]) for row in rows] == [
        (0, 1),
        (1, 0),
    ]
    for row in rows:
        assert row["actor"]["kind"] == "human"
        assert client.get(f"/api/v1/profile/{row['actor']['username']}").json() == row
    assert client.get("/api/v1/profile/owner", headers=headers("reader")).json() == response.json()
    assert "email" not in response.text and "issuer" not in response.text
    assert "subject" not in response.text and "user_id" not in response.text
    assert str(owner_id) not in response.text
    for url in [
        "/api/v1/activity",
        "/api/v1/profile/owner/activity",
        "/api/v1/profile/contributor/activity",
        f"/api/v1/projects/{public}/objects",
    ]:
        public_read = client.get(url)
        assert public_read.status_code == 200, public_read.text
        assert str(owner_id) not in public_read.text
        assert '"author_user_id"' not in public_read.text
        assert '"sponsor_user_id"' not in public_read.text
    assert client.get("/api/v1/profile/OWNER").json()["actor"]["username"] == "owner"
    for token, identity in [("owner", str(owner_id)), ("outsider", empty_id)]:
        for suffix in ("", "/activity"):
            assert client.get(f"/api/v1/profile/{identity}{suffix}").status_code == 404
            assert (
                client.get(
                    f"/api/v1/profile/{identity}{suffix}", headers=headers(token)
                ).status_code
                == 404
            )
    assert client.get(f"/api/v1/profile/{empty_id}").status_code == 404
    assert (
        client.put(
            "/api/v1/account/username", headers=headers("outsider"), json={"username": "outsider"}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/profile/outsider").status_code == 404
    assert client.get("/api/v1/profile/outsider", headers=headers("outsider")).status_code == 200

    hide = client.patch(
        f"/api/v1/projects/{public}",
        headers=headers(),
        json={"visibility": "PRIVATE"},
    )
    assert hide.status_code == 200, hide.text
    assert client.get("/api/v1/profile/owner").status_code == 404
    assert (
        client.get("/api/v1/profile/owner", headers=headers()).json()["authored_contributions"] == 0
    )
    assert client.get("/api/v1/profile/reader").status_code == 404
    for url in ("/api/v1/profiles", "/api/v1/profiles/owner", "/api/v1/profile", "/api/v1/people"):
        assert client.get(url).status_code == 404
        assert client.get(url, headers=headers()).status_code == 404
