from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any, cast
from uuid import UUID

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from research_requests import post_research
from sqlalchemy import select
from sqlalchemy.engine import Engine
from test_catalogue_api import enable
from test_m0_postgresql import pg_schema as pg_schema
from test_publication import headers
from test_research_domain import create_object, create_workspace

from polycolab.app.application import create_app
from polycolab.artifacts.storage import GarageStorage
from polycolab.db.models import (
    SqlArtifact,
    SqlPublicationArtifactMember,
    SqlPublicRelease,
    SqlRecordModeration,
)
from polycolab.platform.config import Settings


class MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs: Any) -> None:
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        data = self.objects[kwargs["Key"]]
        return {"Body": BytesIO(data), "ContentLength": len(data)}

    def delete_object(self, **kwargs: Any) -> None:
        self.objects.pop(kwargs["Key"], None)


def artifact_app(client: TestClient) -> Any:
    app = enable(client)
    app.state.artifact_storage = GarageStorage(MemoryS3(), "publication-test")
    return app


def upload(client: TestClient, project_id: str, data: bytes) -> dict[str, Any]:
    response = client.post(
        "/api/v1/artifacts",
        headers=headers(),
        content=data,
        params={
            "workspace_id": project_id,
            "sha256": hashlib.sha256(data).hexdigest(),
            "byte_length": len(data),
            "media_type": "text/html",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def attach(client: TestClient, project_id: str, artifact_id: str, revision_id: str) -> None:
    response = post_research(
        client,
        "/api/v1/attachments",
        headers=headers(),
        json={"artifact_id": artifact_id, "object_version_id": revision_id, "role": "EVIDENCE"},
    )
    assert response.status_code == 200, response.text


def selection(project_id: str, revision_id: str, artifact_ids: list[str]) -> dict[str, Any]:
    return {
        "workspace_id": project_id,
        "object_version_ids": [revision_id],
        "summary_revision_ids": [],
        "comment_ids": [],
        "progress_ids": [],
        "relation_ids": [],
        "artifact_ids": artifact_ids,
    }


def test_selected_artifact_preview_confirmation_and_public_bytes_are_exact(
    client: TestClient,
) -> None:
    app = artifact_app(client)
    project_id = create_workspace(client)
    target = create_object(client, project_id, title="Artifact-backed result")
    revision_id = target["current_object_version_id"]
    artifact = upload(client, project_id, b"<script>released evidence</script>")
    attach(client, project_id, artifact["id"], revision_id)
    unselected = upload(client, project_id, b"private bytes")
    attach(client, project_id, unselected["id"], revision_id)

    chosen = selection(project_id, revision_id, [artifact["id"]])
    preview = client.post("/api/v1/publication/preview", headers=headers(), json=chosen)
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["selection"]["artifact_ids"] == [artifact["id"]]
    published = preview_body["public_fields"]["artifacts"]
    assert len(published) == 1
    assert published[0] == {
        "id": artifact["id"],
        "sha256": artifact["sha256"],
        "byte_length": artifact["byte_length"],
        "media_type": "text/html",
        "source_object_version_id": None,
        "links": [
            {
                "object_version_id": revision_id,
                "attempt_object_version_id": None,
                "role": "EVIDENCE",
            }
        ],
        "author_display_name": "Owner",
        "actor_kind": "HUMAN",
        "agent_display_name": None,
        "created_at": published[0]["created_at"],
        "content_path": f"/api/v1/artifacts/{artifact['id']}/content",
    }
    confirmed = client.post(
        "/api/v1/publication/confirm",
        headers=headers(key="artifact-publication"),
        json={
            **chosen,
            "preview_digest": preview_body["preview_digest"],
            "reason": "Release the selected verified evidence",
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    manifest_id = confirmed.json()["id"]
    public_manifest = client.get(f"/api/v1/publications/{manifest_id}")
    assert public_manifest.status_code == 200
    assert public_manifest.json()["public_fields"] == preview_body["public_fields"]

    # Retained manifests keep their stored facts but return current download URLs.
    from polycolab.db.models import SqlPublicationManifest

    legacy_path = f"/api/v1/public/artifacts/{artifact['id']}/content"
    with app.state.session_factory() as session:
        manifest = session.get(SqlPublicationManifest, UUID(manifest_id))
        assert manifest is not None
        manifest.public_fields = {
            **manifest.public_fields,
            "artifacts": [
                {**item, "content_path": legacy_path}
                for item in manifest.public_fields["artifacts"]
            ],
        }
        session.commit()
    refreshed = client.get(f"/api/v1/publications/{manifest_id}")
    assert refreshed.json()["public_fields"] == preview_body["public_fields"]
    with app.state.session_factory() as session:
        manifest = session.get(SqlPublicationManifest, UUID(manifest_id))
        assert manifest is not None
        assert manifest.public_fields["artifacts"][0]["content_path"] == legacy_path

    metadata = client.get(f"/api/v1/artifacts/{artifact['id']}")
    assert metadata.status_code == 200
    frozen = preview_body["public_fields"]["artifacts"][0]
    assert metadata.json() == frozen
    content = client.get(f"/api/v1/artifacts/{artifact['id']}/content")
    assert content.status_code == 200
    assert content.content == b"<script>released evidence</script>"
    assert content.headers["content-type"] == "application/octet-stream"
    assert content.headers["x-content-type-options"] == "nosniff"
    assert content.headers["cache-control"] == "private, no-store"
    assert client.get(f"/api/v1/artifacts/{unselected['id']}").status_code == 404

    later = create_object(client, project_id, title="Later private binding")
    attach(client, project_id, artifact["id"], later["current_object_version_id"])
    unchanged = client.get(f"/api/v1/publications/{manifest_id}").json()
    assert unchanged["public_fields"]["artifacts"] == preview_body["public_fields"]["artifacts"]
    assert str(later["current_object_version_id"]) not in str(unchanged)

    with app.state.session_factory() as session:
        assert session.query(SqlPublicRelease).count() == 1


def test_artifact_publication_fails_closed_for_state_scope_bytes_and_stale_preview(
    client: TestClient,
) -> None:
    app = artifact_app(client)
    project_id = create_workspace(client)
    other_project_id = create_workspace(client)
    target = create_object(client, project_id, title="Publication target")
    revision_id = target["current_object_version_id"]
    staged = upload(client, project_id, b"not committed")
    assert (
        client.post(
            "/api/v1/publication/preview",
            headers=headers(),
            json=selection(project_id, revision_id, [staged["id"]]),
        ).status_code
        == 409
    )

    artifact = upload(client, project_id, b"verified bytes")
    attach(client, project_id, artifact["id"], revision_id)
    cross_scope = selection(
        other_project_id,
        create_object(client, other_project_id)["current_object_version_id"],
        [artifact["id"]],
    )
    assert (
        client.post("/api/v1/publication/preview", headers=headers(), json=cross_scope).status_code
        == 404
    )

    chosen = selection(project_id, revision_id, [artifact["id"]])
    first_preview = client.post(
        "/api/v1/publication/preview", headers=headers(), json=chosen
    ).json()
    later = create_object(client, project_id, title="New binding after preview")
    attach(client, project_id, artifact["id"], later["current_object_version_id"])
    stale = client.post(
        "/api/v1/publication/confirm",
        headers=headers(key="stale-artifact-preview"),
        json={
            **chosen,
            "preview_digest": first_preview["preview_digest"],
            "reason": "This preview no longer covers every exact binding",
        },
    )
    assert stale.status_code == 409
    fresh_preview = client.post("/api/v1/publication/preview", headers=headers(), json=chosen)
    assert fresh_preview.status_code == 200
    with app.state.session_factory() as session:
        assert session.query(SqlPublicRelease).count() == 0
        row = session.scalar(select(SqlArtifact).where(SqlArtifact.id == UUID(artifact["id"])))
        assert row is not None
        cast(MemoryS3, app.state.artifact_storage.client).objects.pop(row.storage_key)
    missing_confirmation = client.post(
        "/api/v1/publication/confirm",
        headers=headers(key="missing-artifact-confirmation"),
        json={
            **chosen,
            "preview_digest": fresh_preview.json()["preview_digest"],
            "reason": "The selected bytes disappeared before confirmation",
        },
    )
    assert missing_confirmation.status_code == 503
    missing = client.post("/api/v1/publication/preview", headers=headers(), json=chosen)
    assert missing.status_code == 503
    with app.state.session_factory() as session:
        assert session.query(SqlPublicRelease).count() == 0


def test_public_artifact_download_rechecks_moderation_after_storage_read(
    client: TestClient,
) -> None:
    app = artifact_app(client)
    project_id = create_workspace(client)
    target = create_object(client, project_id, title="Moderated artifact target")
    revision_id = target["current_object_version_id"]
    artifact = upload(client, project_id, b"moderated bytes")
    attach(client, project_id, artifact["id"], revision_id)
    chosen = selection(project_id, revision_id, [artifact["id"]])
    preview = client.post("/api/v1/publication/preview", headers=headers(), json=chosen).json()
    confirmed = client.post(
        "/api/v1/publication/confirm",
        headers=headers(key="moderated-artifact-publication"),
        json={
            **chosen,
            "preview_digest": preview["preview_digest"],
            "reason": "Release before moderation",
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    storage = cast(MemoryS3, app.state.artifact_storage.client)
    original = storage.get_object

    def hide_during_read(**kwargs: Any) -> dict[str, Any]:
        with app.state.session_factory() as session:
            session.add(SqlRecordModeration(object_id=UUID(target["id"]), hidden=True))
            session.commit()
        return original(**kwargs)

    storage.get_object = hide_during_read  # type: ignore[method-assign]
    response = client.get(f"/api/v1/artifacts/{artifact['id']}/content")
    assert response.status_code == 404
    assert response.content != b"moderated bytes"


def test_postgresql_artifact_release_membership_commits_with_exact_release(
    pg_schema: tuple[Engine, Config, str], client: TestClient
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    settings = Settings.model_validate(
        {
            "database_url": url,
            "web_dist_dir": "/missing-artifact-publication-web",
            "artifact_s3_endpoint": "http://127.0.0.1:3900",
            "artifact_s3_bucket": "unused-injected-store",
            "artifact_s3_region": "garage",
            "artifact_s3_access_key": "test-access",
            "artifact_s3_secret_key": "test-secret-value",
        }
    )
    app = create_app(settings, cast(Any, client.app).state.identity_verifier)
    app.state.artifact_storage = GarageStorage(MemoryS3(), "publication-postgresql")
    try:
        with TestClient(app) as pg_client:
            project_id = create_workspace(pg_client)
            target = create_object(pg_client, project_id, title="PostgreSQL artifact result")
            revision_id = target["current_object_version_id"]
            artifact = upload(pg_client, project_id, b"postgresql-bound-bytes")
            attach(pg_client, project_id, artifact["id"], revision_id)
            chosen = selection(project_id, revision_id, [artifact["id"]])
            preview = pg_client.post("/api/v1/publication/preview", headers=headers(), json=chosen)
            assert preview.status_code == 200, preview.text
            confirmed = pg_client.post(
                "/api/v1/publication/confirm",
                headers=headers(key="postgresql-artifact-publication"),
                json={
                    **chosen,
                    "preview_digest": preview.json()["preview_digest"],
                    "reason": "Verify the real publication membership trigger",
                },
            )
            assert confirmed.status_code == 201, confirmed.text
            assert (
                pg_client.get(f"/api/v1/artifacts/{artifact['id']}/content").content
                == b"postgresql-bound-bytes"
            )
        with app.state.session_factory() as session:
            member = session.scalar(
                select(SqlPublicationArtifactMember).where(
                    SqlPublicationArtifactMember.artifact_id == UUID(artifact["id"])
                )
            )
            release = session.scalar(
                select(SqlPublicRelease).where(
                    SqlPublicRelease.object_revision_id == UUID(revision_id)
                )
            )
            assert member is not None and release is not None
            assert member.manifest_id == release.publication_manifest_id
    finally:
        app.state.engine.dispose()
