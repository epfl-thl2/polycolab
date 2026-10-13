"""Opt-in real Docker/TeX Live execution against the real SQLite build API.

Set POLYCOLAB_LATEX_IMAGE to the immutable image ID produced by deploy/latex.
This verifies compiler containment locally, not production deployment acceptance.
"""

import base64
import os
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_sessions_api import create_project, headers

from polycolab.artifacts.storage import FilesystemStorage
from polycolab.document_builds.worker import execute, preflight, reconcile

IMAGE = os.environ.get("POLYCOLAB_LATEX_IMAGE")
pytestmark = pytest.mark.skipif(
    not IMAGE, reason="POLYCOLAB_LATEX_IMAGE is required for real TeX Live execution"
)
WORKER = {"Authorization": "Bearer isolated-test-worker"}


def transport(client: TestClient) -> httpx.MockTransport:
    def send(request: httpx.Request) -> httpx.Response:
        response = client.request(
            request.method, str(request.url), headers=dict(request.headers), content=request.read()
        )
        return httpx.Response(
            response.status_code, headers=response.headers, content=response.content
        )

    return httpx.MockTransport(send)


@pytest.mark.parametrize("engine", ["pdflatex", "lualatex"])
def test_real_texlive_bibliography_and_private_pdf(
    client: TestClient, tmp_path: Path, engine: str
) -> None:
    assert IMAGE
    preflight(IMAGE)
    app = cast(FastAPI, client.app)
    app.state.settings.project_repository_directory = tmp_path / "repos"
    app.state.settings.latex_image = IMAGE
    app.state.settings.latex_worker_token = SecretStr("isolated-test-worker")
    app.state.artifact_storage = FilesystemStorage(tmp_path / "artifacts")
    project = create_project(client)["id"]
    root = f"/api/v1/projects/{project}/worktrees"
    tree = client.get(root, headers=headers("owner")).json()[0]
    root += "/" + tree["id"]
    files = {
        "main.tex": r"""\documentclass{article}
\usepackage{tikz}\usepackage[backend=biber]{biblatex}\addbibresource{refs.bib}
\begin{document}\input{chapter}\cite{sample}
\begin{tikzpicture}\draw (0,0) -- (1,1);\end{tikzpicture}\printbibliography\end{document}""",
        "chapter.tex": "Hello from an immutable worktree snapshot.",
        "refs.bib": "@book{sample, author={Ada Lovelace}, title={Notes}, year={1843}}",
        # A project configuration must never execute, even though latexmk is installed.
        "latexmkrc": "die 'UNTRUSTED RC EXECUTED';",
    }
    saved = client.post(
        root + "/save",
        headers={**headers("owner"), "Idempotency-Key": "sources"},
        json={
            "expected_revision": tree["revision"],
            "changes": [
                {"path": name, "content_base64": base64.b64encode(value.encode()).decode()}
                for name, value in files.items()
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    with httpx.Client(
        base_url="http://testserver", headers=WORKER, transport=transport(client)
    ) as worker:
        worker.post("/internal/latex/ready", json={"image": IMAGE}).raise_for_status()
        response = client.post(
            root + "/latex-builds",
            headers={**headers("owner"), "Idempotency-Key": "build"},
            json={"revision": saved.json()["revision"], "main_file": "main.tex", "engine": engine},
        )
        assert response.status_code == 202, response.text
        claim: dict[str, Any] = worker.post(
            "/internal/latex/claim", json={"worker_id": "real-tex-test"}
        ).json()
        label = "test-" + uuid4().hex
        try:
            execute(worker, claim, label)
        finally:
            reconcile(label)
    path = root + "/latex-builds/" + response.json()["id"]
    result = client.get(path, headers=headers("owner")).json()
    log = client.get(path + "/outputs/log", headers=headers("owner")).text
    assert result["status"] == "succeeded", log
    assert "UNTRUSTED RC EXECUTED" not in log
    assert "biber" in log.lower()
    assert client.get(path + "/outputs/pdf", headers=headers("owner")).content.startswith(b"%PDF-")
    assert client.get(path + "/outputs/pdf", headers=headers("outsider")).status_code == 404


def test_container_limits_and_independent_watchdog() -> None:
    import io
    import json
    import subprocess
    from zipfile import ZipFile

    from polycolab.document_builds.worker import container_command, docker

    assert IMAGE
    label = "test-" + uuid4().hex
    name = "polycolab-latex-watchdog-" + uuid4().hex
    source = io.BytesIO()
    with ZipFile(source, "w") as archive:
        archive.writestr("main.tex", r"\documentclass{article}\begin{document}\loop\iftrue\repeat")
    try:
        docker(*container_command(IMAGE, name, label, "pdflatex", "main.tex", 3))
        config = json.loads(docker("inspect", name))[0]
        host = config["HostConfig"]
        assert host["NetworkMode"] == "none"
        assert host["ReadonlyRootfs"]
        assert host["Memory"] == host["MemorySwap"] == 1024**3
        assert host["NanoCpus"] == 10**9
        assert host["PidsLimit"] == 128
        assert not config["Mounts"]
        assert not any(
            "TOKEN=" in value or "PASSWORD=" in value for value in config["Config"]["Env"]
        )
        # No controller heartbeats or termination: the guest must stop itself.
        output = subprocess.run(
            ["docker", "start", "--attach", "--interactive", name],
            input=source.getvalue(),
            capture_output=True,
            timeout=30,
            check=True,
        ).stdout
        header, _ = output.split(b"\n", 1)
        assert json.loads(header)["status"] == "timed_out"
        assert json.loads(docker("inspect", name))[0]["State"]["Running"] is False
    finally:
        reconcile(label)
