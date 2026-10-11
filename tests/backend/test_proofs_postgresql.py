"""Real PostgreSQL proof-graph locking and migration invariants."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from test_catalogue_api import admit, enable, headers
from test_research_structure import attempt_payload, proof_snapshot, saved_version

from polycolab.accounts.authentication import MappingIdentityVerifier
from polycolab.app.application import create_app
from polycolab.db.models import SqlObjectRevision, SqlRevisionEndorsement
from polycolab.platform.config import Settings
from polycolab.research.contributions import human_contribution


def test_concurrent_proof_edges_cannot_jointly_create_cycle(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-proofs-web"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            enable(pg_client)
            first = admit(pg_client, "cycle-first")
            second = admit(pg_client, "cycle-second")
            barrier = Barrier(2)

            def create(index: int) -> int:
                conclusion, premise = (
                    (first["object_version_id"], second["object_version_id"])
                    if index == 0
                    else (second["object_version_id"], first["object_version_id"])
                )
                barrier.wait(timeout=10)
                response = pg_client.post(
                    "/api/v1/objects",
                    headers=headers(key=f"concurrent-proof-{index}"),
                    json={
                        "destination": {
                            "kind": "library",
                            "statement_object_version_id": conclusion,
                        },
                        "snapshot": proof_snapshot(
                            conclusion, f"Concurrent proof {index}", [premise]
                        ),
                    },
                )
                return int(response.status_code)

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(create, range(2)))
            assert sorted(outcomes) == [201, 409]
    finally:
        app.state.engine.dispose()


def test_proof_and_assurance_history_is_database_immutable(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier
) -> None:
    engine, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-proofs-web"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            enable(pg_client)
            conclusion = admit(pg_client, "immutable-conclusion")
            proof = pg_client.post(
                "/api/v1/objects",
                headers=headers(key="immutable-proof"),
                json={
                    "destination": {
                        "kind": "library",
                        "statement_object_version_id": conclusion["object_version_id"],
                    },
                    "snapshot": proof_snapshot(conclusion["object_version_id"], "Immutable proof"),
                },
            ).json()
            proof = saved_version(pg_client, proof)
            endorsement = pg_client.post(
                "/api/v1/assurance/endorsements",
                headers=headers(key="immutable-endorsement"),
                json={
                    "object_version_id": proof["id"],
                    "active": True,
                    "rationale": "Checked",
                },
            ).json()
            attempt = pg_client.post(
                "/api/v1/objects",
                headers=headers(key="immutable-attempt"),
                json=attempt_payload(
                    target_revision_id=proof["id"],
                    statement_revision_id=conclusion["object_version_id"],
                    title="Immutable attempt",
                ),
            ).json()
            attempt = saved_version(pg_client, attempt)
            note = pg_client.put(
                f"/api/v1/research/objects/{proof['object_id']}/human-note",
                headers=headers(key="immutable-note"),
                json={"body_md": "Immutable note"},
            ).json()
            summary = pg_client.put(
                f"/api/v1/research/objects/{proof['object_id']}/summary",
                headers=headers(key="immutable-summary"),
                json={
                    "body_md": "Immutable summary",
                    "source_object_version_ids": [proof["id"]],
                },
            ).json()
            progress_response = pg_client.post(
                f"/api/v1/research/objects/{proof['object_id']}/progress",
                headers=headers(key="immutable-progress"),
                json={
                    "object_version_id": proof["id"],
                    "status": "COMPLETE",
                    "detail_md": "Reported complete, not verified",
                },
            )
            assert progress_response.status_code == 201, progress_response.text
            progress = progress_response.json()
        for statement, values in (
            (
                "UPDATE proof_sketch_revisions SET reported_progress='PARTIAL' "
                "WHERE revision_id=:revision",
                {
                    "revision": proof["id"],
                },
            ),
            (
                "DELETE FROM revision_endorsements WHERE id=:id",
                {"id": endorsement["id"]},
            ),
            (
                "UPDATE research_attempt_revisions SET findings_md='changed' "
                "WHERE revision_id=:revision",
                {"revision": attempt["id"]},
            ),
            (
                "UPDATE human_note_revisions SET body_md='changed' WHERE id=:id",
                {"id": note["current_revision"]["id"]},
            ),
            (
                "DELETE FROM summary_source_revisions WHERE summary_revision_id=:id",
                {"id": summary["current_revision"]["id"]},
            ),
            (
                "DELETE FROM research_progress_updates WHERE id=:id",
                {"id": progress["id"]},
            ),
        ):
            with engine.begin() as connection:
                try:
                    connection.execute(text(statement), values)
                except DBAPIError as error:
                    assert getattr(error.orig, "sqlstate", None) == "P0001"
                    assert "immutable" in str(error.orig).lower()
                    continue
                raise AssertionError("immutable proof/assurance history accepted a mutation")
    finally:
        app.state.engine.dispose()


def test_postgresql_assurance_uses_time_not_uuid_and_keeps_assessors_independent(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-research-assurance-web"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            enable(pg_client)
            conclusion = admit(pg_client, "postgres-research-assurance-conclusion")
            proof = pg_client.post(
                "/api/v1/objects",
                headers=headers(key="postgres-beta-assurance-proof"),
                json={
                    "destination": {
                        "kind": "library",
                        "statement_object_version_id": conclusion["object_version_id"],
                    },
                    "snapshot": proof_snapshot(
                        conclusion["object_version_id"], "PostgreSQL beta assurance proof"
                    ),
                },
            ).json()
            proof = saved_version(pg_client, proof)
            owner_id = UUID(
                pg_client.get("/api/v1/users/me", headers=headers("owner")).json()["id"]
            )
            contributor_id = UUID(
                pg_client.get("/api/v1/users/me", headers=headers("contributor")).json()["id"]
            )
            with app.state.session_factory() as db:
                revision = db.get(SqlObjectRevision, UUID(proof["id"]))
                assert revision is not None
                start = datetime(2026, 1, 1, tzinfo=UTC)
                for index, (assessor_id, active, rationale) in enumerate(
                    (
                        (owner_id, True, "owner endorses"),
                        (contributor_id, True, "contributor endorses"),
                        (owner_id, False, "owner withdraws"),
                    )
                ):
                    envelope = human_contribution(
                        db,
                        user_id=assessor_id,
                        scope_id=revision.ownership_scope_id,
                        operation="assurance.endorse",
                    )
                    db.add(
                        SqlRevisionEndorsement(
                            id=UUID(int=100 - index),
                            revision_id=revision.id,
                            active=active,
                            rationale=rationale,
                            contribution_id=envelope.id,
                            created_by_user_id=assessor_id,
                            created_at=start + timedelta(seconds=index),
                        )
                    )
                db.commit()

            current_url = f"/api/v1/assurance/{proof['id']}/current"
            current = pg_client.get(current_url)
            assert current.status_code == 200, current.text
            assert {
                (item["assessor_id"], item["active"], item["rationale"])
                for item in current.json()["endorsements"]
            } == {
                (str(owner_id), False, "owner withdraws"),
                (str(contributor_id), True, "contributor endorses"),
            }

            history_url = f"/api/v1/assurance/{proof['id']}"
            rationales: list[str] = []
            cursor = None
            while True:
                response = pg_client.get(
                    history_url,
                    params={"limit": 1, **({"cursor": cursor} if cursor else {})},
                )
                assert response.status_code == 200, response.text
                page = response.json()
                rationales.extend(item["rationale"] for item in page["endorsements"])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            assert rationales == [
                "owner endorses",
                "contributor endorses",
                "owner withdraws",
            ]
    finally:
        app.state.engine.dispose()
