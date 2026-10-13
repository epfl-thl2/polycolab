"""HTTP acceptance for private drafts, immutable releases, and attributed copies."""

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from polycolab.accounts.authentication import MappingIdentityVerifier


def headers(actor: str = "owner", key: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {actor}", "Idempotency-Key": key or str(uuid4())}


def content(text: str = "Check every assumption.") -> dict[str, Any]:
    return {
        "title": "Review a proof",
        "description": "Inspect proof gaps",
        "content": text,
        "tags": ["Proof", "review"],
        "license": "CC-BY-4.0",
    }


def create(
    client: TestClient, kind: str = "PROMPT", data: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/agent-library",
        json={"kind": kind, "content": data or content()},
        headers=headers(),
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_private_public_versions_and_copy(client: TestClient) -> None:
    draft = create(client)
    entry_id = draft["entry"]["id"]
    base = f"/api/v1/agent-library/{entry_id}"
    assert client.get(base).status_code == 404
    assert client.get("/api/v1/agent-library").json()["items"] == []
    assert client.get(base + "/draft").status_code == 401
    assert client.get(base + "/draft", headers=headers("reader")).status_code == 404
    assert (
        client.get(base + "/draft", headers=headers()).headers["cache-control"]
        == "private, no-store"
    )
    assert (
        client.post(
            base + "/publish", json={"expected_revision": 1}, headers=headers("reader")
        ).status_code
        == 404
    )
    key = headers()
    release = client.post(base + "/publish", json={"expected_revision": 1}, headers=key)
    assert release.status_code == 200, release.text
    version = release.json()
    assert (
        client.post(base + "/publish", json={"expected_revision": 1}, headers=key).json() == version
    )
    assert (
        client.post(base + "/publish", json={"expected_revision": 1}, headers=headers()).status_code
        == 409
    )
    public = client.get(base).json()
    assert "draft" not in public and "revision" not in public
    assert public["version"]["content"]["tags"] == ["proof", "review"]
    copied = client.post(
        base + "/copy", json={"version_id": version["id"]}, headers=headers("reader")
    ).json()
    assert copied["entry"]["source_version_id"] == version["id"]
    assert client.get(f"/api/v1/agent-library/{copied['entry']['id']}").status_code == 404
    update = client.put(
        base + "/draft",
        json={"expected_revision": 2, "content": content("PRIVATE NEW DRAFT")},
        headers=headers(),
    )
    assert update.status_code == 200, update.text
    assert "PRIVATE NEW DRAFT" not in client.get(base).text
    assert client.get("/api/v1/agent-library?q=PRIVATE").json()["items"] == []
    next_version = client.post(
        base + "/publish", json={"expected_revision": 3}, headers=headers()
    ).json()
    assert next_version["number"] == 2
    assert client.get(base + f"/versions/{version['id']}").json()["version"] == version
    assert client.get(base + "/versions").json()["items"][0]["number"] == 2
    assert (
        len(client.get("/api/v1/agent-library/yours", headers=headers("reader")).json()["items"])
        == 1
    )


def test_archive_and_moderation_cover_every_public_path(client: TestClient) -> None:
    draft = create(client)
    base = f"/api/v1/agent-library/{draft['entry']['id']}"
    version = client.post(
        base + "/publish", json={"expected_revision": 1}, headers=headers()
    ).json()
    archived = client.post(
        base + "/archive", json={"expected_revision": 2, "archived": True}, headers=headers()
    )
    assert archived.status_code == 200
    assert client.get("/api/v1/agent-library").json()["items"] == []
    assert client.get(base).status_code == 200
    assert (
        client.post(
            base + "/copy", json={"version_id": version["id"]}, headers=headers("reader")
        ).status_code
        == 409
    )
    cast(FastAPI, client.app).state.settings.agent_library_moderator_subjects = ["contributor"]
    body = {"expected_revision": 3, "hidden": True, "reason": "Unsafe instructions"}
    assert client.post(base + "/moderation", json=body, headers=headers()).status_code == 403
    assert (
        client.post(base + "/moderation", json=body, headers=headers("contributor")).status_code
        == 200
    )
    for path in (
        base,
        base + "/versions",
        base + f"/versions/{version['id']}",
        base + f"/versions/{version['id']}/SKILL.md",
    ):
        assert client.get(path).status_code == 404
    assert client.get(base + "/draft", headers=headers()).status_code == 200
    client.post(
        base + "/archive", json={"expected_revision": 4, "archived": False}, headers=headers()
    )
    client.put(
        base + "/draft",
        json={"expected_revision": 5, "content": content("Updated hidden content")},
        headers=headers(),
    )
    assert (
        client.post(base + "/publish", json={"expected_revision": 6}, headers=headers()).status_code
        == 200
    )
    assert client.get(base).status_code == 404
    assert (
        client.post(
            base + "/moderation",
            json={"expected_revision": 7, "hidden": False, "reason": "Reviewed"},
            headers=headers("contributor"),
        ).status_code
        == 200
    )
    assert client.get(base).status_code == 200


def test_skill_plugin_validation_and_download(client: TestClient) -> None:
    skill = "---\nname: proof-review\ndescription: Inspect a proof\n---\n\nCheck assumptions.\n"
    draft = create(client, "SKILL", content(skill))
    base = f"/api/v1/agent-library/{draft['entry']['id']}"
    version = client.post(
        base + "/publish", json={"expected_revision": 1}, headers=headers()
    ).json()
    response = client.get(base + f"/versions/{version['id']}/SKILL.md")
    assert response.status_code == 200 and response.content == skill.encode()
    assert response.headers["content-disposition"] == 'attachment; filename="SKILL.md"'
    for invalid in (
        "No frontmatter",
        "---\nname: Bad Name\ndescription: Test\n---",
        "---\nname: valid\ndescription: &a [*a]\n---",
    ):
        assert (
            client.post(
                "/api/v1/agent-library",
                json={"kind": "SKILL", "content": content(invalid)},
                headers=headers(),
            ).status_code
            == 422
        )
    plugin = {
        **content(),
        "content": "",
        "runtime": "Claude Code",
        "source_url": "https://example.com/plugin",
        "instructions": "Follow the upstream guide.",
        "source_reference": "v1",
    }
    assert create(client, "PLUGIN", plugin)["entry"]["kind"] == "PLUGIN"
    for url in (
        "javascript:alert(1)",
        "https://user:secret@example.com",
        "https://example.com/\nfoo",
    ):
        assert (
            client.post(
                "/api/v1/agent-library",
                json={"kind": "PLUGIN", "content": {**plugin, "source_url": url}},
                headers=headers(),
            ).status_code
            == 422
        )
    no_license = create(client, data={**content(), "license": ""})
    assert (
        client.post(
            f"/api/v1/agent-library/{no_license['entry']['id']}/publish",
            json={"expected_revision": 1},
            headers=headers(),
        ).status_code
        == 422
    )


def test_filter_pagination_and_retry_conflicts(client: TestClient) -> None:
    key = headers()
    body = {"kind": "PROMPT", "content": content()}
    first = client.post("/api/v1/agent-library", json=body, headers=key).json()
    assert client.post("/api/v1/agent-library", json=body, headers=key).json() == first
    assert (
        client.post(
            "/api/v1/agent-library", json={**body, "content": content("different")}, headers=key
        ).status_code
        == 409
    )
    second = create(client)
    for draft in (first, second):
        client.post(
            f"/api/v1/agent-library/{draft['entry']['id']}/publish",
            json={"expected_revision": 1},
            headers=headers(),
        )
    page = client.get("/api/v1/agent-library?limit=1&tag=proof").json()
    assert len(page["items"]) == 1 and page["next_cursor"]
    next_page = client.get(
        "/api/v1/agent-library", params={"limit": 1, "tag": "proof", "cursor": page["next_cursor"]}
    ).json()
    assert next_page["items"][0]["id"] != page["items"][0]["id"]
    assert (
        client.get(
            "/api/v1/agent-library", params={"cursor": page["next_cursor"], "tag": "other"}
        ).status_code
        == 422
    )
    assert client.get("/api/v1/agent-library?q=%25").json()["items"] == []
    assert client.get("/api/v1/agent-library?kind=SKILL").json()["items"] == []


def test_agent_keys_cannot_contribute_and_cross_entry_versions_are_denied(
    client: TestClient,
) -> None:
    agent = client.post(
        "/api/v1/account/agents", json={"name": "Library assistant"}, headers=headers()
    ).json()
    credential = client.post(
        "/api/v1/account/agent-keys",
        json={"name": "Library key", "agent_id": agent["id"]},
        headers=headers(),
    )
    assert credential.status_code == 201
    secret = credential.json()["secret"]
    assert (
        client.post(
            "/api/v1/agent-library",
            json={"kind": "PROMPT", "content": content()},
            headers={"Authorization": f"Bearer {secret}", "Idempotency-Key": str(uuid4())},
        ).status_code
        == 401
    )
    first = create(client)
    second = create(client)
    first_id = first["entry"]["id"]
    second_id = second["entry"]["id"]
    first_version = client.post(
        f"/api/v1/agent-library/{first_id}/publish",
        json={"expected_revision": 1},
        headers=headers(),
    ).json()
    client.post(
        f"/api/v1/agent-library/{second_id}/publish",
        json={"expected_revision": 1},
        headers=headers(),
    )
    assert (
        client.get(f"/api/v1/agent-library/{second_id}/versions/{first_version['id']}").status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/agent-library/{second_id}/copy",
            json={"version_id": first_version["id"]},
            headers=headers("reader"),
        ).status_code
        == 404
    )


def test_unicode_and_quoted_tags_are_searchable(client: TestClient) -> None:
    draft = create(client, data={**content(), "tags": ["géométrie", 'quote"tag']})
    base = f"/api/v1/agent-library/{draft['entry']['id']}"
    assert (
        client.post(base + "/publish", json={"expected_revision": 1}, headers=headers()).status_code
        == 200
    )
    for params in ({"q": "géométrie"}, {"tag": "géométrie"}, {"tag": 'quote"tag'}):
        items = client.get("/api/v1/agent-library", params=params).json()["items"]
        assert len(items) == 1 and items[0]["id"] == draft["entry"]["id"]


def test_library_does_not_require_hosted_execution(client: TestClient) -> None:
    cast(FastAPI, client.app).state.settings.feature_agent_execution_enabled = False
    assert client.get("/api/v1/config").json()["agent_execution"] is False
    draft = create(client)
    base = f"/api/v1/agent-library/{draft['entry']['id']}"
    assert (
        client.post(base + "/publish", json={"expected_revision": 1}, headers=headers()).status_code
        == 200
    )
    assert client.get(base).status_code == 200


def test_migrated_sqlite_protects_public_history(
    tmp_path: Path, identity_verifier: MappingIdentityVerifier
) -> None:
    from sqlalchemy import update
    from sqlalchemy.exc import DBAPIError

    from polycolab.app.application import create_app
    from polycolab.db.models import (
        SqlAgentLibraryEntry,
        SqlAgentLibraryModeration,
        SqlAgentLibraryVersion,
    )
    from polycolab.operations.local_development import upgrade_database
    from polycolab.platform.config import Settings

    database = tmp_path / "library.db"
    upgrade_database(database)
    app = create_app(
        Settings(
            database_url=f"sqlite:///{database}",
            web_dist_dir=str(tmp_path / "missing-web"),
            agent_library_moderator_subjects=["owner"],
        ),
        identity_verifier,
    )
    try:
        with TestClient(app) as real_client:
            draft = create(real_client)
            entry_id = UUID(draft["entry"]["id"])
            base = f"/api/v1/agent-library/{entry_id}"
            version = real_client.post(
                base + "/publish", json={"expected_revision": 1}, headers=headers()
            ).json()
            assert (
                real_client.post(
                    base + "/moderation",
                    json={"expected_revision": 2, "hidden": True, "reason": "Retained decision"},
                    headers=headers(),
                ).status_code
                == 200
            )
        statements = (
            update(SqlAgentLibraryVersion)
            .where(SqlAgentLibraryVersion.id == UUID(version["id"]))
            .values(content=SqlAgentLibraryVersion.content),
            update(SqlAgentLibraryEntry)
            .where(SqlAgentLibraryEntry.id == entry_id)
            .values(kind="PLUGIN"),
            update(SqlAgentLibraryModeration)
            .where(SqlAgentLibraryModeration.entry_id == entry_id)
            .values(reason="Changed history"),
        )
        for statement in statements:
            with pytest.raises(DBAPIError):
                with app.state.engine.begin() as db:
                    db.execute(statement)
    finally:
        app.state.engine.dispose()


def test_kind_specific_fields_cannot_hide_content_from_publication_preview(
    client: TestClient,
) -> None:
    plugin = {
        **content(),
        "runtime": "Claude Code",
        "source_url": "https://example.com/plugin",
        "instructions": "Follow the upstream guide.",
    }
    assert (
        client.post(
            "/api/v1/agent-library", json={"kind": "PLUGIN", "content": plugin}, headers=headers()
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/agent-library",
            json={"kind": "PROMPT", "content": {**content(), "runtime": "Hidden runtime"}},
            headers=headers(),
        ).status_code
        == 422
    )
