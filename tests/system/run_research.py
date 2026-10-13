"""Separate-process research HTTP acceptance with disposable PostgreSQL and Garage.

Run: uv run --directory src/backend python ../../tests/system/run_research.py
No worker/provider/controller runs. Only this invocation's unique Compose project
and API child are removed. Diagnostics never print response bodies or secrets.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, text

from polycolab.agents.external_client import ExternalClient, ServiceError
from polycolab.artifacts.storage import garage_storage
from polycolab.operations.recovery_set import extract_regular_archive

ROOT = Path(__file__).resolve().parents[2]


def claim_snapshot(title: str, content: str) -> dict[str, object]:
    return {
        "kind": "STATEMENT",
        "content": {
            "title": title,
            "content_md": content,
            "assumptions_md": "None stated",
            "reported_outcome": None,
            "explanation_md": None,
        },
        "structural_relationships": [],
        "change_summary": None,
    }


def output_id(receipt: dict, entity_type: str) -> str:
    return next(
        item["entity_id"] for item in receipt["outputs"] if item["entity_type"] == entity_type
    )


def public_research_snapshot(client: httpx.Client, project_id: str) -> dict[str, object]:
    """Capture the bounded fixture's exact public versions and relationship graph."""
    captured: dict[str, object] = {}

    def read(path: str):
        response = client.get(path)
        response.raise_for_status()
        if response.headers.get("X-Next-Cursor"):
            raise RuntimeError("restore_fixture_relationship_bound_invalid")
        value = response.json()
        captured[path] = value
        return value

    objects = read(f"/api/v1/projects/{project_id}/objects?limit=100")
    if objects["next_cursor"] or not objects["items"]:
        raise RuntimeError("restore_fixture_object_bound_invalid")
    for item in objects["items"]:
        history = read(f"/api/v1/objects/{item['id']}/versions?limit=100")
        if history["next_cursor"] or not history["items"]:
            raise RuntimeError("restore_fixture_history_bound_invalid")
        for version in history["items"]:
            exact = f"/api/v1/versions/{version['id']}"
            read(exact)
            read(f"{exact}/relationships")
            read(f"{exact}/attachments")
    return captured


def main() -> int:
    project = "polycolab-check-" + uuid4().hex[:12]
    compose = [
        "docker",
        "compose",
        "-p",
        project,
        "-f",
        str(ROOT / "tests/system/research-compose.yaml"),
    ]
    api = None
    with (
        tempfile.TemporaryFile() as diagnostics,
        tempfile.TemporaryDirectory(prefix="polycolab-browser-results-") as browser_results,
    ):

        def command(args: list[str], **kwargs):
            stage = next(
                (
                    part
                    for part in args
                    if part
                    in {
                        "web:build",
                        "pytest",
                        "polycolab.external_client",
                        "alembic",
                        "test:research",
                        "compose",
                    }
                ),
                Path(args[0]).name,
            )
            print(f"CHECK: {stage}", flush=True)
            return subprocess.run(
                args, check=True, stdout=diagnostics, stderr=diagnostics, timeout=180, **kwargs
            )

        try:
            command(compose + ["up", "-d", "--wait"])

            def port(service: str, internal: str) -> str:
                return (
                    subprocess.check_output(compose + ["port", service, internal], text=True)
                    .strip()
                    .rsplit(":", 1)[1]
                )

            pg_port, garage_port = port("postgres", "5432"), port("garage", "3900")
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                api_port = reservation.getsockname()[1]
            origin = f"http://127.0.0.1:{api_port}"
            env = {
                **os.environ,
                "APP_ENV": "local",
                "WEB_DIST_DIR": str(ROOT / "src/web/dist"),
                "AUTH_MODE": "local",
                "BOOTSTRAP_ADMIN_PASSWORD": "Research-test-password-2026!",
                "REGISTRATION_MODE": "open",
                "PUBLIC_APP_ORIGIN": origin,
                "ALLOWED_ORIGINS": json.dumps([origin]),
                "DATABASE_URL": f"postgresql+psycopg://research:research-test-only@127.0.0.1:{pg_port}/research",
                "FEATURE_AGENT_EXECUTION_ENABLED": "false",
                "FEATURE_VERIFICATION_SUBMISSION_ENABLED": "false",
                "FEATURE_VERIFICATION_EXECUTION_ENABLED": "false",
                "KMS_PROVIDER": "local",
                "ARTIFACT_S3_ENDPOINT": f"http://127.0.0.1:{garage_port}",
                "ARTIFACT_S3_BUCKET": "research-artifacts",
                "ARTIFACT_S3_REGION": "garage",
                "ARTIFACT_S3_ACCESS_KEY": "GK0123456789abcdef0123456789",
                "ARTIFACT_S3_SECRET_KEY": "0123456789abcdef" * 4,
            }
            command(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=ROOT / "src/backend",
                env=env,
            )
            command(
                [sys.executable, "-m", "polycolab.bootstrap_admin"],
                cwd=ROOT / "src/backend",
                env=env,
            )
            browser_enabled = os.environ.get("POLYCOLAB_RESEARCH_BROWSER") == "1"
            reuse_browser_build = os.environ.get("POLYCOLAB_RESEARCH_REUSE_WEB_BUILD") == "1"
            if browser_enabled and reuse_browser_build:
                if not (ROOT / "src/web/dist/index.html").is_file():
                    raise RuntimeError("production_browser_build_required")
            if browser_enabled and not reuse_browser_build:
                command(
                    ["pnpm", "run", "web:build"],
                    cwd=ROOT,
                    env={**os.environ},
                )
            api = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "polycolab.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--no-access-log",
                ],
                cwd=ROOT / "src/backend",
                env=env,
                stdout=diagnostics,
                stderr=diagnostics,
            )
            with httpx.Client(
                base_url=origin, headers={"Origin": origin}, timeout=10, trust_env=False
            ) as human:
                ready_deadline = time.monotonic() + 60
                while time.monotonic() < ready_deadline:
                    if api.poll() is not None:
                        raise RuntimeError("api_start_failed")
                    try:
                        if human.get("/health/ready").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError("api_ready_timeout")

                if browser_enabled:
                    browser_entry = human.get("/signup")
                    if (
                        browser_entry.status_code != 200
                        or "text/html" not in browser_entry.headers.get("content-type", "")
                    ):
                        raise RuntimeError("production_browser_entry_unavailable")

                def post(path: str, body: dict):
                    response = human.post(
                        path, json=body, headers={"Idempotency-Key": str(uuid4())}
                    )
                    if response.status_code not in {200, 201}:
                        raise RuntimeError(f"human_operation_failed:{response.status_code}:{path}")
                    return response.json()

                post(
                    "/auth/login",
                    {"username": "admin", "password": "Research-test-password-2026!"},
                )
                project = post("/api/v1/projects", {"name": "External research acceptance"})
                claim = post(
                    "/api/v1/objects",
                    {
                        "destination": {"kind": "project", "project_id": project["id"]},
                        "snapshot": claim_snapshot(
                            "Example input", "A public test claim, not a theorem."
                        ),
                    },
                )
                identity = post("/api/v1/account/agents", {"name": "Separate client"})
                credential = post(
                    "/api/v1/account/agent-keys",
                    {"name": "Separate client", "agent_id": identity["id"]},
                )
                # Opt-in interactive acceptance: a real externally running agent
                # consumes the credential privately and performs its own API work.
                interactive = os.environ.get("POLYCOLAB_RESEARCH_AGENT_SESSION_DIR")
                if interactive:
                    session_dir = Path(interactive)
                    if (
                        not session_dir.is_absolute()
                        or session_dir.resolve() != session_dir
                        or not session_dir.is_dir()
                        or session_dir.stat().st_mode & 0o077
                    ):
                        raise RuntimeError("private_agent_session_directory_required")
                    agent_input = post(
                        "/api/v1/objects",
                        {
                            "destination": {"kind": "project", "project_id": project["id"]},
                            "snapshot": claim_snapshot(
                                "Sum of the first n odd integers",
                                "For every integer n >= 1, the sum of 2k-1 "
                                "for k=1,...,n equals n squared.",
                            ),
                        },
                    )
                    context = {
                        "service_url": origin,
                        "credential": credential["secret"],
                        "project_id": project["id"],
                        "input_object_id": output_id(agent_input, "RESEARCH_OBJECT"),
                        "input_object_version_id": output_id(agent_input, "OBJECT_VERSION"),
                    }
                    with (session_dir / "connection.json").open("x") as output:
                        os.chmod(session_dir / "connection.json", 0o600)
                        json.dump(context, output)
                    print("READY: external agent session; credentials stored privately", flush=True)
                    for _ in range(3600):
                        if (session_dir / "DONE").exists():
                            break
                        time.sleep(1)
                    else:
                        raise RuntimeError("external_agent_session_timeout")
                    revoked = human.delete(f"/api/v1/account/agent-keys/{credential['id']}")
                    if revoked.status_code != 204:
                        raise RuntimeError("live_agent_revoke_failed")
                    with httpx.Client(base_url=origin, trust_env=False) as anonymous:
                        denied = anonymous.get(
                            "/api/v1/me",
                            headers={"Authorization": f"Bearer {credential['secret']}"},
                        )
                        if denied.status_code != 401:
                            raise RuntimeError("live_agent_revocation_not_enforced")
                        public = anonymous.get(f"/api/v1/projects/{project['id']}/objects")
                        if public.status_code != 200:
                            raise RuntimeError("live_agent_public_reread_failed")
                    print("PASS: interactive agent contribution followed by revocation/public read")
                    return 0
                # Deliberately no inherited database, cookies, KMS or worker config.
                client_env = {
                    "PATH": os.environ["PATH"],
                    "POLYCOLAB_SERVICE_URL": origin,
                    "POLYCOLAB_AGENT_CREDENTIAL": credential["secret"],
                }
                request_id = str(uuid4())
                invocation = [
                    sys.executable,
                    "-m",
                    "polycolab.external_client",
                    "--request-id",
                    request_id,
                ]
                for _ in range(2):
                    command(
                        invocation
                        + [
                            "--input-object-version",
                            output_id(claim, "OBJECT_VERSION"),
                            "--project-id",
                            project["id"],
                        ],
                        cwd=ROOT / "src/backend",
                        env=client_env,
                    )
                probe = ExternalClient(origin, credential["secret"])
                try:
                    payload = {
                        "destination": {"kind": "project", "project_id": project["id"]},
                        "snapshot": claim_snapshot("Probe", "Probe content"),
                    }
                    created = probe.request(
                        "POST",
                        "/api/v1/objects",
                        key="probe-object",
                        json=payload,
                    )
                    object_id = output_id(created, "RESEARCH_OBJECT")
                    object_version_id = output_id(created, "OBJECT_VERSION")

                    def denied(method, path, statuses, **kwargs):
                        try:
                            probe.request(method, path, **kwargs)
                        except ServiceError as error:
                            if error.status in statuses:
                                return
                            raise
                        raise RuntimeError("expected_denial_missing")

                    denied(
                        "POST",
                        "/api/v1/objects",
                        {409},
                        key="probe-object",
                        json={
                            **payload,
                            "snapshot": claim_snapshot("Conflicting retry", "Probe content"),
                        },
                    )
                    edit = {
                        "expected_current_object_version_id": object_version_id,
                        "snapshot": claim_snapshot("New base", "Changed"),
                    }
                    probe.request(
                        "POST",
                        f"/api/v1/objects/{object_id}/versions",
                        key="edit-first",
                        json=edit,
                    )
                    denied(
                        "POST",
                        f"/api/v1/objects/{object_id}/versions",
                        {409},
                        key="edit-stale",
                        json=edit,
                    )
                    probe.request(
                        "POST",
                        "/api/v1/relations",
                        key="probe-equivalence",
                        json={
                            "destination": {
                                "kind": "project",
                                "project_id": project["id"],
                            },
                            "direction": "BIDIRECTIONAL",
                            "relationship_type": "EQUIVALENT_TO",
                            "first_object_version_id": object_version_id,
                            "second_object_version_id": output_id(claim, "OBJECT_VERSION"),
                            "description": "Recovery fixture declaration; not verified equivalence",
                        },
                    )
                    data = b"Staged evidence must not be public"
                    params = {
                        "project_id": project["id"],
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "byte_length": len(data),
                    }
                    staged = probe.request(
                        "POST",
                        "/api/v1/artifacts",
                        key="stage-only",
                        content=data,
                        params=params,
                    )
                    denied("GET", f"/api/v1/artifacts/{staged['id']}/content", {404}, raw=True)
                    denied(
                        "POST",
                        "/api/v1/artifacts",
                        {409, 422},
                        key="bad-digest",
                        content=data,
                        params={**params, "sha256": "0" * 64},
                    )
                    probe.request(
                        "POST",
                        "/api/v1/attachments",
                        key="commit-probe",
                        json={
                            "artifact_id": staged["id"],
                            "object_version_id": object_version_id,
                            "role": "EVIDENCE",
                        },
                    )
                    content_path = f"/api/v1/artifacts/{staged['id']}/content"
                    if probe.request("GET", content_path, raw=True) != data:
                        raise RuntimeError("committed_probe_mismatch")
                    # Fault injection belongs only to the test orchestrator; the
                    # separate external client still has no DB/storage credential.
                    engine = create_engine(env["DATABASE_URL"])
                    try:
                        with engine.connect() as connection:
                            storage_key = connection.execute(
                                text("SELECT storage_key FROM artifacts WHERE id = :id"),
                                {"id": staged["id"]},
                            ).scalar_one()
                    finally:
                        engine.dispose()
                    storage = garage_storage(
                        endpoint=env["ARTIFACT_S3_ENDPOINT"],
                        bucket="research-artifacts",
                        region="garage",
                        access_key=env["ARTIFACT_S3_ACCESS_KEY"],
                        secret_key=env["ARTIFACT_S3_SECRET_KEY"],
                    )
                    try:
                        storage.client.put_object(
                            Bucket=storage.bucket, Key=storage_key, Body=b"corrupt"
                        )
                        denied("GET", content_path, {503}, raw=True)
                        storage.client.delete_object(Bucket=storage.bucket, Key=storage_key)
                        denied("GET", content_path, {503}, raw=True)
                    finally:
                        storage.client.put_object(Bucket=storage.bucket, Key=storage_key, Body=data)
                        storage.client.close()
                    if probe.request("GET", content_path, raw=True) != data:
                        raise RuntimeError("probe_repair_failed")
                finally:
                    probe.close()
                revoked = human.delete(f"/api/v1/account/agent-keys/{credential['id']}")
                if revoked.status_code != 204:
                    raise RuntimeError("revoke_failed")
                command(invocation + ["--expect-revoked"], cwd=ROOT / "src/backend", env=client_env)
                with httpx.Client(base_url=origin, trust_env=False) as anonymous:
                    response = anonymous.get(f"/api/v1/projects/{project['id']}/objects")
                    if response.status_code != 200:
                        raise RuntimeError("public_read_after_revoke_failed")
                restored_credential_response = human.post(
                    "/api/v1/account/agent-keys",
                    json={"name": "Restore invalidation probe", "agent_id": identity["id"]},
                )
                if restored_credential_response.status_code != 201:
                    raise RuntimeError("restore_probe_credential_failed")
                restored_credential = restored_credential_response.json()
                if browser_enabled:
                    command(
                        [
                            "pnpm",
                            "--filter",
                            "@polycolab/web",
                            "exec",
                            "playwright",
                            "test",
                            "--config",
                            str(ROOT / "tests/system/playwright.config.ts"),
                            str(ROOT / "tests/system/specs/public-agent-real-service.spec.ts"),
                            *(
                                ["--grep", os.environ["POLYCOLAB_RESEARCH_BROWSER_GREP"]]
                                if os.environ.get("POLYCOLAB_RESEARCH_BROWSER_GREP")
                                else []
                            ),
                            "--trace",
                            "off",
                            "--output",
                            browser_results,
                        ],
                        cwd=ROOT,
                        env={
                            **os.environ,
                            "POLYCOLAB_INTEGRATION_API_URL": origin,
                            "POLYCOLAB_INTEGRATION_WEB_URL": origin,
                            "POLYCOLAB_INTEGRATION_RESEARCH": "1",
                        },
                    )
                    print("PASS: selected production browser journeys")
            command(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "../../tests/backend/test_external_agents_postgresql.py",
                    "../../tests/backend/test_agent_library_postgresql.py",
                    "../../tests/backend/test_project_migration.py",
                    "-q",
                ],
                cwd=ROOT / "src/backend",
                env={
                    **env,
                    "M0_POSTGRES_TEST_URL": env["DATABASE_URL"],
                },
            )
            # Real encrypted PostgreSQL drill, deliberately separate from full
            # Garage/key recovery acceptance. Restore only into this test server.
            if os.environ.get("POLYCOLAB_RESEARCH_ENCRYPTED_DB_DRILL") == "1":
                with httpx.Client(base_url=origin, trust_env=False, timeout=10) as anonymous:
                    expected_research = public_research_snapshot(anonymous, project["id"])
                probe_history = expected_research[f"/api/v1/objects/{object_id}/versions?limit=100"]
                if not isinstance(probe_history, dict) or len(probe_history["items"]) != 2:
                    raise RuntimeError("restore_fixture_requires_multiple_versions")
                directions = {
                    relationship["direction"]
                    for path, relationships in expected_research.items()
                    if path.endswith("/relationships") and isinstance(relationships, list)
                    for relationship in relationships
                }
                if directions != {"UNIDIRECTIONAL", "BIDIRECTIONAL"}:
                    raise RuntimeError("restore_fixture_requires_both_relationship_directions")
                api.terminate()
                api.wait(timeout=15)
                api = None
                command(compose + ["stop", "garage"])
                with tempfile.TemporaryDirectory(prefix="polycolab-db-drill-") as raw:
                    temporary = Path(raw)
                    identity = temporary / "identity"
                    command(["age-keygen", "-o", str(identity)])
                    recipient = subprocess.check_output(
                        ["age-keygen", "-y", str(identity)], text=True
                    ).strip()
                    dump = temporary / "dump"
                    with dump.open("wb") as output:
                        subprocess.run(
                            compose
                            + [
                                "exec",
                                "-T",
                                "postgres",
                                "pg_dump",
                                "-U",
                                "research",
                                "-d",
                                "research",
                                "-Fc",
                                "--no-owner",
                                "--no-acl",
                            ],
                            stdout=output,
                            stderr=diagnostics,
                            check=True,
                            timeout=60,
                        )
                    dump.chmod(0o600)
                    encrypted = temporary / "dump.age"
                    command(["age", "-r", recipient, "-o", str(encrypted), str(dump)])
                    restored = temporary / "restored.dump"
                    command(["age", "-d", "-i", str(identity), "-o", str(restored), str(encrypted)])
                    if (
                        hashlib.sha256(dump.read_bytes()).digest()
                        != hashlib.sha256(restored.read_bytes()).digest()
                    ):
                        raise RuntimeError("encrypted_dump_mismatch")
                    command(
                        compose
                        + ["exec", "-T", "postgres", "createdb", "-U", "research", "recovery_set"]
                    )
                    with restored.open("rb") as source:
                        command(
                            compose
                            + [
                                "exec",
                                "-T",
                                "postgres",
                                "pg_restore",
                                "-U",
                                "research",
                                "-d",
                                "recovery_set",
                                "--no-owner",
                                "--no-acl",
                                "--exit-on-error",
                            ],
                            stdin=source,
                        )
                    restored_database_url = (
                        env["DATABASE_URL"].removesuffix("/research") + "/recovery_set"
                    )
                    command(
                        [
                            sys.executable,
                            "-m",
                            "polycolab.operator_restore_invalidation",
                            "--confirm-restored-cohort-invalidation",
                            "--recovery-reference",
                            "research-restore-drill",
                        ],
                        cwd=ROOT / "src/backend",
                        env={**env, "DATABASE_URL": restored_database_url},
                    )
                    result = subprocess.check_output(
                        compose
                        + [
                            "exec",
                            "-T",
                            "postgres",
                            "psql",
                            "-U",
                            "research",
                            "-d",
                            "recovery_set",
                            "-Atc",
                            "SELECT count(*) FROM external_agent_credentials "
                            "WHERE revoked_at IS NULL",
                        ],
                        text=True,
                    ).strip()
                    if result != "0":
                        raise RuntimeError("restored_credential_unexpectedly_active")
                    result = subprocess.check_output(
                        compose
                        + [
                            "exec",
                            "-T",
                            "postgres",
                            "psql",
                            "-U",
                            "research",
                            "-d",
                            "recovery_set",
                            "-Atc",
                            "SELECT count(*) FROM auth_sessions WHERE revoked_at IS NULL",
                        ],
                        text=True,
                    ).strip()
                    if result != "0":
                        raise RuntimeError("restored_session_unexpectedly_active")
                    restore_compose = compose + ["--profile", "restore"]
                    command(restore_compose + ["create", "garage-restore"])
                    for part in ("meta", "data"):
                        source_dir = temporary / f"garage-{part}"
                        source_dir.mkdir()
                        command(
                            compose + ["cp", f"garage:/var/lib/garage/{part}/.", str(source_dir)]
                        )
                        archive = temporary / f"{part}.tar"
                        with tarfile.open(archive, "w") as output:
                            output.add(source_dir, arcname=".")
                        encrypted_archive = temporary / f"{part}.tar.age"
                        command(
                            ["age", "-r", recipient, "-o", str(encrypted_archive), str(archive)]
                        )
                        decrypted_archive = temporary / f"{part}.restored.tar"
                        command(
                            [
                                "age",
                                "-d",
                                "-i",
                                str(identity),
                                "-o",
                                str(decrypted_archive),
                                str(encrypted_archive),
                            ]
                        )
                        if (
                            hashlib.sha256(archive.read_bytes()).digest()
                            != hashlib.sha256(decrypted_archive.read_bytes()).digest()
                        ):
                            raise RuntimeError("garage_archive_mismatch")
                        staged = temporary / f"restored-{part}"
                        extract_regular_archive(decrypted_archive, staged, 100 * 1024**2, 10000)
                        command(
                            restore_compose
                            + ["cp", str(staged) + "/.", f"garage-restore:/var/lib/garage/{part}"]
                        )
                    command(restore_compose + ["up", "-d", "--wait", "garage-restore"])
                    restored_port = port("garage-restore", "3900")
                    restored_env = {
                        **env,
                        "DATABASE_URL": restored_database_url,
                        "ARTIFACT_S3_ENDPOINT": f"http://127.0.0.1:{restored_port}",
                    }
                    api = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "polycolab.main:app",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(api_port),
                            "--no-access-log",
                        ],
                        cwd=ROOT / "src/backend",
                        env=restored_env,
                        stdout=diagnostics,
                        stderr=diagnostics,
                    )
                    with httpx.Client(base_url=origin, trust_env=False, timeout=10) as restored_api:
                        for _ in range(100):
                            try:
                                if restored_api.get("/health/ready").status_code == 200:
                                    break
                            except httpx.TransportError:
                                pass
                            time.sleep(0.2)
                        page = restored_api.get(f"/api/v1/projects/{project['id']}/artifacts")
                        page.raise_for_status()
                        for item in page.json()["items"]:
                            metadata = item["artifact"]
                            content = restored_api.get(
                                f"/api/v1/artifacts/{metadata['id']}/content"
                            )
                            content.raise_for_status()
                            if hashlib.sha256(content.content).hexdigest() != metadata["sha256"]:
                                raise RuntimeError("restored_public_artifact_mismatch")
                        if not page.json()["items"]:
                            raise RuntimeError("restored_artifacts_missing")
                        if (
                            public_research_snapshot(restored_api, project["id"])
                            != expected_research
                        ):
                            raise RuntimeError(
                                "restored_research_versions_or_relationships_mismatch"
                            )
                        denied = restored_api.get(
                            "/api/v1/me",
                            headers={"Authorization": f"Bearer {restored_credential['secret']}"},
                        )
                        if denied.status_code != 401:
                            raise RuntimeError("restored_revocation_failed")
                print(
                    "PASS: encrypted PostgreSQL/Garage restore, "
                    "exact version history, relationships, public byte digests "
                    "and global protected-access invalidation"
                )
            print(
                "PASS: separate HTTP client, real PostgreSQL/Garage, evidence, retry and revocation"
            )
            return 0
        except Exception as error:
            print(f"FAIL: research harness ({type(error).__name__}); diagnostics suppressed")
            if isinstance(error, subprocess.CalledProcessError):
                print(f"Failed executable: {Path(error.cmd[0]).name}; exit {error.returncode}")
                diagnostics.seek(0)
                import re

                for line in diagnostics.read().decode(errors="replace").splitlines():
                    if "Error:" in line or re.search(r"spec\.ts:\d+", line):
                        print(re.sub(r"pca_[A-Za-z0-9_-]+", "[REDACTED]", line)[:500])
            if isinstance(error, RuntimeError):
                print(str(error))
            return 1
        finally:
            if api is not None:
                api.terminate()
                try:
                    api.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    api.kill()
                    api.wait()
            subprocess.run(
                compose + ["--profile", "restore", "down", "--volumes"],
                stdout=diagnostics,
                stderr=diagnostics,
                timeout=120,
                check=False,
            )


if __name__ == "__main__":
    raise SystemExit(main())
