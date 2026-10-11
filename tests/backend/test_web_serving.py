from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import AnyUrl

from polycolab.accounts.authentication import MappingIdentityVerifier
from polycolab.app.application import create_app
from polycolab.platform.config import AuthMode, Environment, Settings


def test_new_public_routes_reach_handlers_and_retain_rate_limits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = cast(FastAPI, client.app)
    app.state.settings.public_read_requests_per_minute = 1
    monkeypatch.setattr(
        "polycolab.app.application.utc_now", lambda: datetime(2026, 9, 5, tzinfo=UTC)
    )

    response = client.get("/api/v1/catalogue")
    assert response.status_code == 200
    limited = client.get("/api/v1/library")
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0


def test_removed_public_project_routes_stay_blocked(client: TestClient) -> None:
    for path in (
        "/api/v1/public/projects",
        "/api/v1/public/projects/probe",
        "/public/workspaces",
        "/public/projects/probe/objects/probe",
        "/api/v1/workspaces/probe/objects/probe/neighborhood",
    ):
        for method in ("GET", "POST"):
            assert client.request(method, path).status_code in (404, 405)


def test_private_and_unknown_public_pages_have_the_same_non_disclosing_response(
    client: TestClient,
) -> None:
    project = client.post(
        "/api/v1/workspaces",
        headers={"Authorization": "Bearer owner"},
        json={"visibility": "PRIVATE", "name": "Private project"},
    )
    assert project.status_code == 201

    private = client.get(f"/public/projects/{project.json()['id']}")
    unknown = client.get("/public/projects/00000000-0000-0000-0000-000000000001")
    assert private.status_code == unknown.status_code == 404
    assert private.json()["error"]["code"] == unknown.json()["error"]["code"]


def test_auth_config_exposes_only_browser_safe_public_metadata(client: TestClient) -> None:
    cast(FastAPI, client.app).state.settings.auth_mode = AuthMode.LOCAL
    response = client.get("/auth/config")
    assert response.status_code == 200
    assert response.json() == {
        "mode": "local",
        "social_providers": [],
        "registration_mode": "closed",
    }
    for secret_key in ("jwks_url", "authorized_party", "client_secret"):
        assert secret_key not in response.text

    oidc_app = create_app(
        Settings(
            app_env=Environment.LOCAL,
            auth_mode=AuthMode.OIDC,
            database_url="sqlite+pysqlite:///:memory:",
            oidc_issuer=AnyUrl("https://identity.example"),
            oidc_jwks_url=AnyUrl("https://identity.example/jwks"),
            oidc_client_id="polycolab-web",
            oidc_audience="polycolab-api",
        ),
        MappingIdentityVerifier({}),
    )
    with TestClient(oidc_app) as oidc_client:
        assert oidc_client.get("/auth/config").json() == {
            "mode": "oidc",
            "issuer": "https://identity.example",
            "client_id": "polycolab-web",
            "audience": "polycolab-api",
        }
    oidc_app.state.engine.dispose()


def test_vite_assets_and_spa_fallback_do_not_swallow_service_routes(tmp_path: Path) -> None:
    web_dist = tmp_path / "web-dist"
    assets = web_dist / "assets"
    assets.mkdir(parents=True)
    (web_dist / "index.html").write_text("<html>vite shell</html>", encoding="utf-8")
    (assets / "polycolab.js").write_text("window.polycolab = true", encoding="utf-8")
    svelte_assets = web_dist / "_app" / "immutable"
    svelte_assets.mkdir(parents=True)
    (svelte_assets / "start.js").write_text("export const app = 'svelte'", encoding="utf-8")

    docs = web_dist / "docs"
    (docs / "getting-started").mkdir(parents=True)
    (docs / "api").mkdir(parents=True)
    (docs / "setup" / "external-agent").mkdir(parents=True)
    (docs / "developers" / "agent-runs").mkdir(parents=True)
    (docs / "index.html").write_text("<html>documentation</html>")
    (docs / "getting-started" / "index.html").write_text("<html>getting started</html>")
    (docs / "api" / "index.html").write_text("<html>API reference documentation</html>")
    (docs / "setup" / "external-agent" / "index.html").write_text(
        "<html>external agent setup</html>"
    )
    (docs / "developers" / "agent-runs" / "index.html").write_text("<html>agent runs</html>")
    (docs / "search.json").write_text("{}")

    app = create_app(
        Settings(
            app_env=Environment.LOCAL,
            auth_mode=AuthMode.LOCAL,
            database_url="sqlite+pysqlite:///:memory:",
            public_read_requests_per_minute=0,
            web_dist_dir=str(web_dist),
        ),
        MappingIdentityVerifier({}),
    )
    with TestClient(app) as vite_client:
        root = vite_client.get("/")
        for browser_path in (
            "/about",
            "/search",
            "/people",
            "/chat",
            "/activity",
            "/activity/recent",
            "/activity/workspaces",
            "/library",
            "/library/statement",
            "/workspaces",
            "/workspaces/example",
            "/workspaces?scope=public",
            "/workspaces/example/objects/claim",
        ):
            browser_response = vite_client.get(browser_path)
            assert browser_response.status_code == 200
            assert browser_response.text == "<html>vite shell</html>"
        assert vite_client.get("/public/workspaces-other").status_code == 404
        route = vite_client.get("/projects/example")
        asset = vite_client.get("/assets/polycolab.js")
        assert root.status_code == route.status_code == asset.status_code == 200
        assert "vite shell" in root.text
        assert "vite shell" in route.text
        assert vite_client.get("/SKILL.md").status_code == 404
        skill_source = Path(__file__).resolve().parents[2] / "skills/polycolab/SKILL.md"
        (web_dist / "SKILL.md").write_bytes(skill_source.read_bytes())
        skill = vite_client.get("/SKILL.md")
        assert skill.status_code == 200
        assert skill.content == skill_source.read_bytes()
        assert skill.headers["content-type"] == "text/markdown; charset=utf-8"
        assert skill.headers["cache-control"] == "no-cache"
        assert skill.headers["x-content-type-options"] == "nosniff"
        assert vite_client.get("/skill.md").status_code == 404
        assert "window.polycolab" in asset.text
        svelte_asset = vite_client.get("/_app/immutable/start.js")
        assert svelte_asset.status_code == 200
        assert "javascript" in svelte_asset.headers["content-type"]
        assert "export const app" in svelte_asset.text
        assert vite_client.get("/_app/immutable/missing.js").status_code == 404

        for path in ("/docs", "/docs/"):
            assert "documentation" in vite_client.get(path).text
        assert "external agent setup" in vite_client.get("/docs/setup/external-agent/").text
        assert "application/json" in vite_client.get("/docs/search.json").headers["content-type"]
        assert vite_client.get("/docs/missing").status_code == 404
        assert vite_client.get("/docs/missing.js").status_code == 404
        assert "API reference documentation" in vite_client.get("/docs/api").text
        for old, target in (
            ("/guide", "/docs/getting-started/"),
            ("/connect", "/docs/setup/external-agent/"),
            ("/docs/connect", "/docs/setup/external-agent/"),
            ("/docs/agent-api", "/docs/developers/agent-runs/"),
        ):
            redirect = vite_client.get(old, follow_redirects=False)
            assert redirect.status_code == 307
            assert redirect.headers["location"] == target

        for reserved in (
            "/api/v1/unknown",
            "/auth/unknown",
            "/health/unknown",
            "/internal/unknown",
            "/public/unknown",
        ):
            response = vite_client.get(reserved)
            assert response.status_code == 404
            assert "vite shell" not in response.text

        post = vite_client.post("/projects/example")
        assert post.status_code == 405
        assert "vite shell" not in post.text
    app.state.engine.dispose()
