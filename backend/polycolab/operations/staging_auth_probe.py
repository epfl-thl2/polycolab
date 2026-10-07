"""Content-free staging authentication boundary probe; no login or state writes."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping

import httpx


def probe(environment: Mapping[str, str], client: httpx.Client) -> bool:
    """Require anonymous denial and an authenticated read with the selected mode."""
    origin = httpx.URL(environment.get("STAGING_BASE_URL", ""))
    if (
        origin.scheme != "https"
        or not origin.host
        or origin.userinfo
        or origin.query
        or origin.fragment
        or origin.path != "/"
    ):
        raise ValueError("invalid staging origin")
    mode = environment.get("STAGING_AUTH_MODE") or "local"
    if mode == "local":
        name = environment.get("STAGING_AUTH_COOKIE_NAME") or "polycolab_session"
        secret = environment.get("STAGING_OPERATOR_SESSION", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise ValueError("invalid cookie name")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,4096}", secret):
            raise ValueError("invalid session")
        headers = {"Cookie": f"{name}={secret}"}
    elif mode == "oidc":
        secret = environment.get("STAGING_OPERATOR_TOKEN", "")
        if not re.fullmatch(r"[A-Za-z0-9_.~-]{1,16384}", secret):
            raise ValueError("invalid token")
        headers = {"Authorization": f"Bearer {secret}"}
    else:
        raise ValueError("unsupported authentication mode")
    endpoint = origin.join("/api/v1/projects")
    # Stream responses without reading private project lists or error bodies.
    # Redirects must never carry credentials to a different destination.
    client.cookies.clear()
    with client.stream("GET", endpoint, follow_redirects=False) as response:
        if response.status_code != 401:
            return False
    client.cookies.clear()
    with client.stream("GET", endpoint, headers=headers, follow_redirects=False) as response:
        return response.status_code == 200


def main() -> int:
    try:
        with httpx.Client(trust_env=False, timeout=15) as client:
            verified = probe(os.environ, client)
    except Exception:
        verified = False
    print(json.dumps({"status": "VERIFIED" if verified else "AUTH_BOUNDARY_FAILURE"}))
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
