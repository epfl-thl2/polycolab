"""Static reference checks, not a live Keycloak import or OIDC acceptance test."""

import json
from pathlib import Path


def test_optional_realm_matches_browser_paths_and_token_boundary() -> None:
    root = Path(__file__).resolve().parents[2]
    realm = json.loads((root / "deploy/keycloak/polycolab-realm.json").read_text())
    assert realm["sslRequired"] == "all"
    assert realm["registrationAllowed"] is False
    assert "users" not in realm
    (client,) = realm["clients"]
    assert client["publicClient"] and client["standardFlowEnabled"]
    for key in ("implicitFlowEnabled", "directAccessGrantsEnabled", "serviceAccountsEnabled"):
        assert client[key] is False
    assert "secret" not in client
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    browser = (root / "src/web/src/svelte-lib/auth.svelte.ts").read_text()
    assert client["redirectUris"] == [
        "https://polycolab.example.org/oidc/callback",
        "https://polycolab.example.org/oidc/silent-callback",
    ]
    assert "/oidc/callback" in browser and "/oidc/silent-callback" in browser
    assert client["webOrigins"] == ["https://polycolab.example.org"]
    (mapper,) = client["protocolMappers"]
    assert mapper["protocolMapper"] == "oidc-audience-mapper"
    assert mapper["config"] == {
        "included.custom.audience": "polycolab-api",
        "access.token.claim": "true",
        "id.token.claim": "false",
    }
