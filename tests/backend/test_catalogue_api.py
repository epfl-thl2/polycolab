from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from research_requests import post_research
from sqlalchemy import func, select

from polycolab.access.actors import ActorOperation, agent_actor
from polycolab.access.authorization import AuthorizationDenied
from polycolab.catalogue import admission as catalogue
from polycolab.catalogue.schemas import (
    CatalogueAdmit,
    CatalogueModerate,
    CatalogueModeratorUpdate,
    CataloguePromote,
    CatalogueRevise,
)
from polycolab.db.models import (
    SqlCatalogueAudit,
    SqlCatalogueEntry,
    SqlCatalogueModeratorAudit,
    SqlCatalogueRevision,
    SqlContributionEnvelope,
    SqlMutationReceipt,
    SqlObjectRevision,
    SqlOutboxEvent,
    SqlPublicRelease,
    SqlResearchObject,
    SqlResearchScope,
    SqlUser,
)
from polycolab.entities.enums import ResearchObjectKind, ResearchScopeKind
from polycolab.platform.outbox import canonical_digest
from polycolab.research.objects import create_object


def enable(client: TestClient) -> Any:
    app = cast(Any, client.app)
    app.state.settings.catalogue_operator_subjects = ["owner"]
    with app.state.session_factory() as db:
        if (
            db.scalar(
                select(SqlResearchScope).where(
                    SqlResearchScope.scope_kind == ResearchScopeKind.COMMONS
                )
            )
            is None
        ):
            db.add(SqlResearchScope(scope_kind=ResearchScopeKind.COMMONS))
            db.commit()
    return app


def formulation() -> dict[str, Any]:
    return {
        "kind": "STATEMENT",
        "title": "A sourced claim",
        "content_md": "For all n, ...",
        "assumptions_md": "n is a positive integer",
        "reported_status": "Open in the cited source",
        "source": {
            "identifier": "arXiv:1234.56789",
            "version": "v2",
            "locator": "Conjecture 3, p. 7",
        },
        "reason": "Record the exact formulation from the source",
    }


def headers(user: str = "owner", key: str = "admit") -> dict[str, str]:
    return {"Authorization": f"Bearer {user}", "Idempotency-Key": key}


def admit(client: TestClient, key: str = "admit") -> dict[str, str]:
    response = client.post("/api/v1/catalogue", headers=headers(key=key), json=formulation())
    assert response.status_code == 201, response.text
    assert set(response.json()) == {"entry_id", "object_version_id"}
    return cast(dict[str, str], response.json())


def test_catalogue_admission_revision_moderation_and_revocation(client: TestClient) -> None:
    app = enable(client)
    first = admit(client)
    assert admit(client) == first
    entry_id = first["entry_id"]
    url = f"/api/v1/catalogue/{entry_id}"
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["object_version"]["id"] == first["object_version_id"]
    assert response.json()["source"] == formulation()["source"]
    for forbidden in (
        "workspace_id",
        "session_id",
        "run_id",
        "membership",
        "credential",
    ):
        assert forbidden not in response.text
    version = response.json()["object_version"]
    assert version == client.get(f"/api/v1/versions/{first['object_version_id']}").json()
    assert version["authorship"]["contribution_id"] is None
    assert version["authorship"]["author_user_id"] is None
    assert version["authorship"]["sponsor_user_id"] is None
    assert "statement" not in response.json()
    assert "revision_number" not in response.json()
    edit = formulation()
    edit.pop("kind")
    edit.update(
        expected_current_object_version_id=first["object_version_id"],
        title="A corrected formulation",
    )
    path = f"/api/v1/catalogue/{entry_id}/versions"
    assert client.post(path, headers=headers("outsider", "edit"), json=edit).status_code == 403
    revised = client.post(path, headers=headers(key="edit"), json=edit)
    assert revised.status_code == 201, revised.text
    assert revised.json()["object_version_id"] != first["object_version_id"]
    assert client.post(path, headers=headers(key="edit"), json=edit).json() == revised.json()
    assert client.post(path, headers=headers(key="stale"), json=edit).status_code == 409
    historical_edit = {
        **{
            key: value for key, value in edit.items() if key != "expected_current_object_version_id"
        },
        "base_revision_id": first["object_version_id"],
    }
    assert (
        client.post(path, headers=headers(key="old-shape"), json=historical_edit).status_code == 422
    )
    assert (
        client.post(
            f"{url}/revisions", headers=headers(key="old-path"), json=historical_edit
        ).status_code
        == 404
    )
    assert (
        client.get(f"{url}/versions/{first['object_version_id']}").json()["object_version"][
            "content"
        ]["title"]
        == formulation()["title"]
    )
    with app.state.session_factory() as db:
        receipt = db.scalar(
            select(SqlMutationReceipt).where(
                SqlMutationReceipt.idempotency_key_digest == canonical_digest("edit")
            )
        )
        assert receipt is not None
        assert receipt.request_digest == canonical_digest(
            {"schema_version": 1, "entry_id": entry_id, "payload": historical_edit}
        )
    assert client.get(url).json()["object_version"]["content"]["title"] == "A corrected formulation"

    moderator = client.get("/api/v1/users/me", headers=headers("contributor")).json()["id"]
    assignment = f"/api/v1/catalogue-moderators/{moderator}"
    grant = {"active": True, "reason": "Appoint a moderator"}
    assert client.put(assignment, headers=headers("outsider"), json=grant).status_code == 403
    assert client.put(assignment, headers=headers(), json=grant).status_code == 204
    moderation = {
        "expected_current_object_version_id": revised.json()["object_version_id"],
        "action": "HIDE",
        "reason": "Abusive content report",
    }
    path = f"/api/v1/catalogue/{entry_id}/moderation"
    assert client.post(path, headers=headers(key="hide"), json=moderation).status_code == 403
    assert (
        client.post(path, headers=headers("contributor", "hide"), json=moderation).status_code
        == 200
    )
    assert (
        client.post(path, headers=headers("contributor", "hide"), json=moderation).status_code
        == 200
    )
    historical_moderation = {
        "base_revision_id": moderation["expected_current_object_version_id"],
        "action": "HIDE",
        "reason": moderation["reason"],
    }
    assert (
        client.post(
            path, headers=headers("contributor", "legacy"), json=historical_moderation
        ).status_code
        == 422
    )
    assert (
        client.post(
            path,
            headers=headers("contributor", "stale-hide"),
            json={**moderation, "expected_current_object_version_id": first["object_version_id"]},
        ).status_code
        == 409
    )
    with app.state.session_factory() as db:
        receipt = db.scalar(
            select(SqlMutationReceipt).where(
                SqlMutationReceipt.idempotency_key_digest == canonical_digest("hide")
            )
        )
        assert receipt is not None
        assert receipt.request_digest == canonical_digest(
            {"schema_version": 1, "entry_id": entry_id, "payload": historical_moderation}
        )
    assert client.get(url).status_code == 404
    hidden_html = client.get(f"/library/{entry_id}")
    assert hidden_html.status_code == 404
    assert client.get(f"/library/{uuid4()}").status_code == 404
    assert client.get("/api/v1/catalogue").json()["items"] == []
    audit_path = f"/api/v1/catalogue/{entry_id}/audit"
    audit = client.get(audit_path, headers=headers("contributor"))
    assert {item["action"] for item in audit.json()} == {"ADMIT", "REVISE", "HIDE"}
    assert {item["object_version_id"] for item in audit.json()} == {
        first["object_version_id"],
        revised.json()["object_version_id"],
    }
    assert all("revision_id" not in item for item in audit.json())
    moderation["action"] = "RESTORE"
    assert (
        client.post(path, headers=headers("contributor", "restore"), json=moderation).status_code
        == 200
    )
    assert client.get(url).status_code == 200
    assert (
        client.put(
            assignment, headers=headers(), json={"active": False, "reason": "Revoke role"}
        ).status_code
        == 204
    )
    # Replays reauthorize: an old receipt cannot restore revoked authority.
    assert (
        client.post(path, headers=headers("contributor", "restore"), json=moderation).status_code
        == 403
    )
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(SqlCatalogueEntry)) == 1
        assert db.scalar(select(func.count()).select_from(SqlCatalogueRevision)) == 2
        assert db.scalar(select(func.count()).select_from(SqlCatalogueModeratorAudit)) == 2
        assert db.scalar(select(func.count()).select_from(SqlPublicRelease)) == 2


@pytest.mark.parametrize(
    "field", ["title", "content_md", "assumptions_md", "reported_status", "reason"]
)
def test_catalogue_rejects_blank_formulation(client: TestClient, field: str) -> None:
    enable(client)
    payload = formulation()
    payload[field] = " \n "
    assert client.post("/api/v1/catalogue", headers=headers(), json=payload).status_code == 422


@pytest.mark.parametrize("field", ["identifier", "version", "locator"])
def test_catalogue_requires_source_parts(client: TestClient, field: str) -> None:
    enable(client)
    payload = formulation()
    del payload["source"][field]
    assert client.post("/api/v1/catalogue", headers=headers(), json=payload).status_code == 422


def test_catalogue_available_with_identity_and_changed_retry(client: TestClient) -> None:
    response = client.get("/api/v1/catalogue")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    enable(client)
    assert client.post("/api/v1/catalogue", json=formulation()).status_code == 401
    first = admit(client)
    payload = formulation()
    payload["title"] = "Changed retry"
    assert client.post("/api/v1/catalogue", headers=headers(), json=payload).status_code == 409
    payload["actor_kind"] = "HUMAN"
    assert (
        client.post("/api/v1/catalogue", headers=headers(key="forged"), json=payload).status_code
        == 422
    )
    assert client.get(f"/api/v1/catalogue/{first['entry_id']}").status_code == 200
    assert client.get(f"/library/{first['entry_id']}").status_code == 404


def test_agent_cannot_admit_or_assign_moderators(client: TestClient) -> None:
    app = enable(client)
    user_id = UUID(client.get("/api/v1/users/me", headers=headers()).json()["id"])
    actor = agent_actor(
        sponsor_user_id=user_id,
        agent_version_id=uuid4(),
        run_id=uuid4(),
        capability_id=uuid4(),
        session_id=uuid4(),
        context_manifest_id=uuid4(),
        project_id=uuid4(),
        operation_scope=frozenset(ActorOperation),
    )
    with app.state.session_factory() as db:
        edit = formulation()
        edit.pop("kind")
        edit["base_revision_id"] = uuid4()
        source = CatalogueAdmit.model_validate({**formulation(), "kind": "CLAIM"}).source
        assert source is not None
        for payload in (
            CatalogueAdmit.model_validate({**formulation(), "kind": "CLAIM"}),
            CatalogueRevise.model_validate(edit),
            CataloguePromote(
                revision_id=uuid4(),
                source=source,
                reported_status="Open",
                reason="Promote",
            ),
            CatalogueModerate(base_revision_id=uuid4(), action="HIDE", reason="Hide"),
        ):
            with pytest.raises(AuthorizationDenied):
                catalogue.mutate(
                    db,
                    actor=actor,
                    settings=app.state.settings,
                    idempotency_key="agent",
                    payload=payload,
                    entry_id=uuid4(),
                )
        with pytest.raises(AuthorizationDenied):
            catalogue.assign_moderator(
                db,
                actor=actor,
                settings=app.state.settings,
                user_id=user_id,
                payload=CatalogueModeratorUpdate(active=True, reason="Sponsor is operator"),
            )


def test_catalogue_failure_rolls_back_everything(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = enable(client)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected catalogue outbox failure")

    monkeypatch.setattr(catalogue, "append_event", fail)
    assert (
        client.post("/api/v1/catalogue", headers=headers(), json=formulation()).status_code == 500
    )
    with app.state.session_factory() as db:
        for model in (
            SqlCatalogueEntry,
            SqlCatalogueRevision,
            SqlCatalogueAudit,
            SqlResearchObject,
            SqlObjectRevision,
            SqlPublicRelease,
            SqlContributionEnvelope,
            SqlMutationReceipt,
            SqlOutboxEvent,
        ):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_catalogue_reads_pin_release_instead_of_later_draft(client: TestClient) -> None:
    from polycolab.research.contributions import human_contribution
    from polycolab.research.objects import add_revision_metadata

    app = enable(client)
    first = admit(client)
    with app.state.session_factory() as db:
        obj = db.get(SqlResearchObject, UUID(first["entry_id"]))
        base = db.get(SqlObjectRevision, UUID(first["object_version_id"]))
        assert obj is not None and base is not None
        envelope = human_contribution(
            db,
            user_id=base.created_by_user_id,
            scope_id=obj.ownership_scope_id,
            operation="unreleased-draft",
        )
        draft = SqlObjectRevision(
            object_id=obj.id,
            ownership_scope_id=obj.ownership_scope_id,
            base_revision_id=base.id,
            number=base.number + 1,
            title="UNRELEASED SECRET",
            content_md="UNRELEASED SECRET",
            contribution_id=envelope.id,
            created_by_user_id=base.created_by_user_id,
        )
        db.add(draft)
        db.flush()
        add_revision_metadata(db, obj, draft)
        obj.current_revision_id = draft.id
        db.commit()
    for path in (f"/api/v1/catalogue/{first['entry_id']}",):
        response = client.get(path)
        assert response.status_code == 200
        assert "UNRELEASED SECRET" not in response.text
        assert "A sourced claim" in response.text


def test_catalogue_pagination_and_untrusted_title_json(client: TestClient) -> None:
    enable(client)
    for index in range(3):
        admit(client, f"page-{index}")
    first = client.get("/api/v1/catalogue?limit=2").json()
    assert len(first["items"]) == 2
    second = client.get(
        "/api/v1/catalogue", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    assert len({row["entry_id"] for row in first["items"] + second["items"]}) == 3
    assert client.get("/api/v1/catalogue?cursor=invalid").status_code == 422
    payload = formulation()
    payload["title"] = '<script>alert("x")</script>'
    created = client.post("/api/v1/catalogue", headers=headers(key="html"), json=payload).json()
    read = client.get(f"/api/v1/catalogue/{created['entry_id']}")
    assert read.json()["object_version"]["content"]["title"] == payload["title"]


def test_catalogue_reads_share_public_rate_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    app = enable(client)
    entry = admit(client)
    app.state.settings.public_read_requests_per_minute = 1
    monkeypatch.setattr(
        "polycolab.app.application.utc_now", lambda: datetime(2026, 9, 6, tzinfo=UTC)
    )
    assert client.get(f"/api/v1/catalogue/{entry['entry_id']}").status_code == 200
    limited = client.get("/api/v1/library")
    assert limited.status_code == 429
    assert limited.headers["cache-control"] == "private, no-store"
    assert int(limited.headers["retry-after"]) > 0


def test_promotion_preserves_public_supporting_identity_and_denies_private(
    client: TestClient,
) -> None:
    app = enable(client)
    client.get("/api/v1/users/me", headers=headers())
    with app.state.session_factory() as db:
        user = db.scalar(select(SqlUser).where(SqlUser.subject == "owner"))
        scope = db.scalar(
            select(SqlResearchScope).where(SqlResearchScope.scope_kind == ResearchScopeKind.COMMONS)
        )
        assert user is not None and scope is not None
        obj, revision = create_object(
            db,
            ownership_scope_id=scope.id,
            author=user,
            kind=ResearchObjectKind.CLAIM,
            title="Supporting",
            content_md="Claim",
            assumptions_md="No additional assumptions",
            rationale=None,
            commit=False,
        )
        original_id, revision_id = obj.id, revision.id
        envelope = db.get(SqlContributionEnvelope, obj.contribution_id)
        assert envelope is not None
        catalogue._release(db, obj, revision, envelope)
        db.commit()
    payload = {
        "object_version_id": str(revision_id),
        "source": formulation()["source"],
        "reported_status": "Open",
        "reason": "Promote supporting statement",
    }
    response = client.post("/api/v1/catalogue/promotions", headers=headers(), json=payload)
    assert response.status_code == 201, response.text
    assert response.json() == {"entry_id": str(original_id), "object_version_id": str(revision_id)}
    assert (
        client.post("/api/v1/catalogue/promotions", headers=headers(), json=payload).json()
        == response.json()
    )
    historical_promotion = {
        **{key: value for key, value in payload.items() if key != "object_version_id"},
        "revision_id": str(revision_id),
    }
    assert (
        client.post(
            "/api/v1/catalogue/promotions", headers=headers(key="legacy"), json=historical_promotion
        ).status_code
        == 422
    )
    with app.state.session_factory() as db:
        receipt = db.scalar(
            select(SqlMutationReceipt).where(
                SqlMutationReceipt.idempotency_key_digest == canonical_digest("admit"),
                SqlMutationReceipt.operation == "catalogue.promote",
            )
        )
        assert receipt is not None
        assert receipt.request_digest == canonical_digest(
            {"schema_version": 1, "entry_id": "None", "payload": historical_promotion}
        )
    project = client.post(
        "/api/v1/workspaces", headers=headers(), json={"visibility": "PRIVATE", "name": "Private"}
    ).json()
    private = post_research(
        client,
        "/api/v1/objects",
        headers=headers(),
        json={
            "destination": {"kind": "workspace", "workspace_id": project["id"]},
            "snapshot": {
                "kind": "STATEMENT",
                "content": {
                    "title": "Secret",
                    "content_md": "Secret",
                    "assumptions_md": "None",
                    "reported_outcome": None,
                    "explanation_md": None,
                },
                "structural_relationships": [],
            },
        },
    ).json()
    payload["object_version_id"] = private["current_object_version_id"]
    denied = client.post(
        "/api/v1/catalogue/promotions", headers=headers(key="private"), json=payload
    )
    assert denied.status_code == 404


def test_library_reads_only_admitted_statements(
    client: TestClient,
) -> None:
    enable(client)
    admitted = admit(client)
    workspace = client.post(
        "/api/v1/workspaces",
        headers=headers(),
        json={"visibility": "PRIVATE", "name": "Unreviewed workspace"},
    ).json()
    assert (
        post_research(
            client,
            "/api/v1/objects",
            headers=headers(),
            json={
                "destination": {"kind": "workspace", "workspace_id": workspace["id"]},
                "snapshot": {
                    "kind": "STATEMENT",
                    "content": {
                        "title": "Unreviewed claim",
                        "content_md": "Draft",
                        "assumptions_md": "None",
                        "reported_outcome": None,
                        "explanation_md": None,
                    },
                    "structural_relationships": [],
                },
            },
        ).status_code
        == 201
    )
    page = client.get("/api/v1/catalogue")
    assert page.status_code == 200
    assert page.headers["Cache-Control"] == "private, no-store"
    assert [item["entry_id"] for item in page.json()["items"]] == [admitted["entry_id"]]
    assert client.get(f"/api/v1/catalogue/{admitted['entry_id']}").status_code == 200
    assert client.post("/api/v1/catalogue", json=formulation()).status_code == 401
    assert client.get("/api/v1/catalogue").status_code == 200
