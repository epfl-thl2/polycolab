from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import AnyUrl, SecretStr

from polycolab.accounts.authentication import MappingIdentityVerifier, Principal
from polycolab.app.application import create_app
from polycolab.app.export_openapi import DEFAULT_OUTPUT, serialized_openapi
from polycolab.db.base import Base
from polycolab.platform.config import (
    ApiReferenceAccess,
    AuthMode,
    Environment,
    KmsProvider,
    Settings,
)


def test_openapi_has_versioned_operations_security_and_error_envelopes(client: TestClient) -> None:
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    document = response.json()
    assert document["openapi"].startswith("3.")
    assert document["components"]["securitySchemes"]["BearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "Human OIDC token",
    }
    assert document["components"]["securitySchemes"]["ExternalAgentBearer"]["scheme"] == ("bearer")
    assert document["components"]["schemas"]["ErrorEnvelope"]["required"] == ["error"]
    operation_ids: list[str] = []
    for path, path_item in document["paths"].items():
        assert path.startswith("/api/v1/")
        for operation in path_item.values():
            operation_ids.append(operation["operationId"])
            assert operation["tags"]
            assert "$ref" in operation["responses"]["404"]["content"]["application/json"]["schema"]
            assert "security" in operation
            if path.startswith("/api/v1/runs"):
                assert operation["security"] == [{"ExternalAgentBearer": []}]
            if (
                operation["operationId"].startswith("list")
                and operation["responses"]["200"]
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
                .get("type")
                == "array"
            ):
                headers = operation["responses"]["200"]["headers"]
                assert {"X-Next-Cursor", "X-Total-Count"} <= set(headers)
    assert len(operation_ids) == len(set(operation_ids))
    normalized_paths = [re.sub(r"\{[^}]+\}", "{}", path) for path in document["paths"]]
    assert len(normalized_paths) == len(set(normalized_paths))
    assert "400" in document["paths"]["/api/v1/invitations/accept"]["post"]["responses"]
    assert (
        "503" in document["paths"]["/api/v1/projects/{project_id}/invitations"]["post"]["responses"]
    )


def test_research_version_contract_has_no_legacy_revision_fields() -> None:
    document = json.loads(serialized_openapi())
    # These are independent note/summary histories, not research object versions.
    independent_histories = {
        "RepositoryRunState": {"input_revision", "output_revision"},
        "RepositoryMerge": {"expected_target_revision", "expected_source_revision"},
        "RepositoryMergePreview": {"target_revision", "source_revision"},
        "WorktreeCommit": {"expected_revision"},
        "WorktreeRead": {"revision"},
        "WorktreeRemove": {"expected_revision"},
        "WorktreeRevision": {"expected_revision"},
        "WorktreeSave": {"expected_revision"},
        "WorktreeSaved": {"revision"},
        "HumanNoteRead": {"current_revision"},
        "HumanNoteRevisionRead": {"base_revision_id"},
        "HumanNoteWrite": {"base_revision_id"},
        "PublicPublicationVersionSelection": {"summary_revision_ids"},
        "PublicationVersionConfirm": {"summary_revision_ids"},
        "PublicationVersionSelection": {"summary_revision_ids"},
        "ResearchSummaryVersionRead": {"current_revision"},
        "ResearchSummaryVersionRevisionRead": {"base_revision_id"},
        "ResearchSummaryVersionWrite": {"base_revision_id"},
    }
    actual = {
        name: {field for field in schema.get("properties", {}) if "revision" in field}
        for name, schema in document["components"]["schemas"].items()
        if any("revision" in field for field in schema.get("properties", {}))
    }
    assert actual == independent_histories


def test_openapi_tags_match_resource_boundaries() -> None:
    document = json.loads(serialized_openapi())
    paths = document["paths"]
    assert paths["/api/v1/me"]["get"]["tags"] == ["identity"]
    assert paths["/api/v1/account/agent-keys"]["post"]["tags"] == ["agent-keys"]
    assert "post" not in paths["/api/v1/runs"]
    assert paths["/api/v1/agent-runs/{run_id}"]["get"]["tags"] == ["agent-runs"]
    assert paths["/api/v1/projects"]["get"]["tags"] == ["projects"]
    assert paths["/api/v1/projects"]["post"]["tags"] == ["projects"]
    assert paths["/api/v1/catalogue/{entry_id}/audit"]["get"]["tags"] == ["catalogue"]
    assert paths["/api/v1/catalogue-moderators/{user_id}"]["put"]["tags"] == ["moderation"]
    assert paths["/api/v1/research/objects/{object_id}/human-note"]["get"]["tags"] == ["context"]
    assert "Human authentication required" in paths["/api/v1/projects"]["post"]["description"]
    assert "Idempotency-Key" in paths["/api/v1/objects"]["post"]["description"]
    assert "X-Run-ID" not in paths["/api/v1/objects"]["post"]["description"]
    assert (
        "Optional deployment capability" in paths["/api/v1/platform-agents"]["get"]["description"]
    )


def test_reference_groups_cover_every_operation_once_without_empty_sections() -> None:
    document = json.loads(serialized_openapi())
    groups = document["x-tagGroups"]
    assert groups[0]["name"] == "Access"
    assert all(group["tags"] for group in groups)
    grouped_tags = [tag for group in groups for tag in group["tags"]]
    assert len(grouped_tags) == len(set(grouped_tags))
    operations = [operation for item in document["paths"].values() for operation in item.values()]
    assert all(len(operation["tags"]) == 1 for operation in operations)
    assert all(operation["summary"] and operation["description"] for operation in operations)
    used_tags = {operation["tags"][0] for operation in operations}
    assert used_tags == set(grouped_tags) == {tag["name"] for tag in document["tags"]}
    assert all(tag["description"] for tag in document["tags"])
    assert "## Start here" in document["info"]["description"]
    assert "pca_" in document["info"]["description"]


def test_reference_omits_sections_when_their_operations_are_absent() -> None:
    from polycolab.app.reference import arrange_reference

    document: dict[str, Any] = {
        "paths": {
            "/api/v1/me": {
                "get": {
                    "operationId": "getCurrentIdentity",
                    "security": [{"ExternalAgentBearer": []}],
                }
            }
        }
    }
    arrange_reference(document)
    assert document["x-tagGroups"] == [{"name": "Access", "tags": ["identity"]}]
    assert [tag["name"] for tag in document["tags"]] == ["identity"]


def test_list_pagination_uses_opaque_cursor_headers_and_stable_order(client: TestClient) -> None:
    project = client.post(
        "/api/v1/projects",
        headers={"Authorization": "Bearer owner"},
        json={"visibility": "PRIVATE", "name": "Pages"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]
    for title in ("one", "two", "three"):
        response = client.post(
            "/api/v1/objects",
            headers={"Authorization": "Bearer owner", "Idempotency-Key": title},
            json={
                "destination": {"kind": "project", "project_id": project_id},
                "snapshot": {
                    "kind": "STATEMENT",
                    "content": {
                        "title": title,
                        "content_md": title,
                        "assumptions_md": "None",
                        "reported_outcome": None,
                        "explanation_md": None,
                    },
                    "structural_relationships": [],
                },
            },
        )
        assert response.status_code == 201
    first = client.get(
        f"/api/v1/projects/{project_id}/objects?limit=2",
        headers={"Authorization": "Bearer owner"},
    )
    assert first.status_code == 200
    assert "x-total-count" not in first.headers
    assert len(first.json()["items"]) == 2
    cursor = first.json()["next_cursor"]
    second = client.get(
        f"/api/v1/projects/{project_id}/objects?limit=2&cursor={cursor}",
        headers={"Authorization": "Bearer owner"},
    )
    assert second.status_code == 200
    assert len(second.json()["items"]) == 1
    assert "x-next-cursor" not in second.headers
    assert {
        item["current_object_version"]["content"]["title"]
        for item in first.json()["items"] + second.json()["items"]
    } == {
        "one",
        "two",
        "three",
    }
    malformed = client.get(
        f"/api/v1/projects/{project_id}/objects?cursor=not-a-cursor",
        headers={"Authorization": "Bearer owner"},
    )
    assert malformed.status_code == 422


def test_openapi_snapshot_is_the_deterministic_application_contract() -> None:
    assert DEFAULT_OUTPUT.is_file()
    assert DEFAULT_OUTPUT.read_text(encoding="utf-8") == serialized_openapi()
    parsed = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    assert parsed["info"]["title"] == "Polycolab application service"


def test_local_scalar_reference_is_constrained(client: TestClient) -> None:
    response = client.get("/api/reference/content")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "connect-src 'self'" in response.headers["content-security-policy"]
    for expected in (
        '"proxyUrl":""',
        '"telemetry":false',
        '"persistAuth":false',
        '"hideClientButton":true',
        '"showDeveloperTools":"never"',
        '"defaultOpenFirstTag":false',
        '"hideTestRequestButton":true',
        '"agent":{"disabled":true}',
        '"mcp":{"disabled":true}',
        '"pluginUrls":[]',
        '"url":"/api/openapi.json"',
        "--scalar-color-accent: #007480;",
        "--scalar-button-1: #007480;",
        "@scalar/api-reference@1.62.6",
        "sha384-N7JUv0+P4dgRu102bnNFxOXOXp2ROTMToXk71fUs0MNI1wZpfxZYHVAJTnVMS19o",
    ):
        assert expected in response.text
    configuration = client.get("/api/reference/config")
    assert configuration.status_code == 200
    assert configuration.headers["cache-control"] == "no-store"
    assert configuration.json()["spec"] == {"url": "/api/openapi.json"}
    assert configuration.json()["telemetry"] is False


@pytest.mark.parametrize(
    "reference_path", ["/docs/api/", "/api/reference/content", "/api/reference/config"]
)
def test_production_scalar_honors_explicit_access_mode_and_legacy_operator_mode(
    tmp_path: Path,
    reference_path: str,
) -> None:
    def production_settings(
        *,
        access: ApiReferenceAccess | None = None,
        enabled: bool | None = None,
        operator_subjects: list[str] | None = None,
    ) -> Settings:
        return Settings(
            app_env=Environment.PRODUCTION,
            auth_mode=AuthMode.OIDC,
            database_url=f"sqlite+pysqlite:///{tmp_path / 'contract.sqlite'}",
            oidc_issuer=AnyUrl("https://issuer.example"),
            oidc_jwks_url=AnyUrl("https://issuer.example/jwks"),
            oidc_audience="polycolab",
            oidc_client_id="polycolab-web",
            kms_provider=KmsProvider.AWS,
            kms_key_id="test-kms-key",
            admission_scope_hmac_key=SecretStr("test-admission-scope-key"),
            runtime_worker_token=SecretStr("test-runtime-worker-token"),
            api_reference_access=access,
            api_reference_enabled=enabled,
            api_reference_operator_subjects=operator_subjects or [],
        )

    verifier = MappingIdentityVerifier(
        {
            "owner": Principal("https://issuer.example", "owner"),
            "outsider": Principal("https://issuer.example", "outsider"),
        }
    )
    disabled = create_app(production_settings(), verifier)
    Base.metadata.create_all(disabled.state.engine)
    with TestClient(disabled) as disabled_client:
        assert disabled_client.get(reference_path).status_code == 404
    Base.metadata.drop_all(disabled.state.engine)
    disabled.state.engine.dispose()

    public = create_app(
        production_settings(access=ApiReferenceAccess.PUBLIC),
        verifier,
    )
    Base.metadata.create_all(public.state.engine)
    with TestClient(public) as public_client:
        assert public_client.get(reference_path).status_code == 200
    Base.metadata.drop_all(public.state.engine)
    public.state.engine.dispose()

    operators = create_app(
        production_settings(
            access=ApiReferenceAccess.OPERATORS,
            operator_subjects=["owner"],
        ),
        verifier,
    )
    Base.metadata.create_all(operators.state.engine)
    with TestClient(operators) as operators_client:
        assert operators_client.get(reference_path).status_code == 401
        assert (
            operators_client.get(
                reference_path, headers={"Authorization": "Bearer outsider"}
            ).status_code
            == 403
        )
        assert (
            operators_client.get(
                reference_path, headers={"Authorization": "Bearer owner"}
            ).status_code
            == 200
        )
    Base.metadata.drop_all(operators.state.engine)
    operators.state.engine.dispose()

    enabled = create_app(
        production_settings(enabled=True, operator_subjects=["owner"]),
        verifier,
    )
    Base.metadata.create_all(enabled.state.engine)
    with TestClient(enabled) as enabled_client:
        assert enabled_client.get(reference_path).status_code == 401
        assert (
            enabled_client.get(
                reference_path, headers={"Authorization": "Bearer outsider"}
            ).status_code
            == 403
        )
        assert (
            enabled_client.get(
                reference_path, headers={"Authorization": "Bearer owner"}
            ).status_code
            == 200
        )
    Base.metadata.drop_all(enabled.state.engine)
    enabled.state.engine.dispose()


def test_legacy_api_reference_redirects(client: TestClient) -> None:
    response = client.get("/api/reference", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs/api/"


def test_public_project_vocabulary_does_not_change_stored_payload_keys() -> None:
    from uuid import uuid4

    from polycolab.projects.schemas import ProjectVersionCopyCreate

    document = json.loads(serialized_openapi())
    for path, methods in document["paths"].items():
        assert "workspace" not in path
        for operation in methods.values():
            assert "Workspace" not in operation["operationId"]
            assert all(
                parameter["name"] != "workspace_id" for parameter in operation.get("parameters", [])
            )
    for name, schema in document["components"]["schemas"].items():
        assert "Workspace" not in name
        assert "workspace_id" not in schema.get("properties", {})
    project_id, version_id = uuid4(), uuid4()
    request = ProjectVersionCopyCreate.model_validate(
        {"project_id": str(project_id), "source_object_version_id": str(version_id)}
    )
    assert request.model_dump(mode="json", by_alias=True)["project_id"] == str(project_id)
    stored = request.historical_command().model_dump(mode="json")
    assert stored["project_id"] == str(project_id)
    assert "workspace_id" not in stored
