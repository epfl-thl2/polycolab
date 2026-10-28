# LaTeX compilation

Compilation is available in Git-mode projects. Linear-history projects do not yet
have a compilation interface.

The API owns permissions, worktree snapshots, the durable queue, and build metadata.
A separate host process claims builds through authenticated private HTTP endpoints.
Each build runs TeX Live and latexmk in a fresh Docker container. This feature does
not require an agent session, model provider, or the hosted-agent VM controller.

## Local setup

Docker Desktop must be running with Linux containers and cgroup v2. Run commands
from the repository root. Building the full TeX Live image downloads several
GB on a cold cache. The default uses the official frozen TeX Live 2025 image
for Linux/amd64, including Docker Desktop emulation on Apple Silicon. For native
Linux/arm64, build with `-f deploy/latex/Dockerfile.native`; that alternative installs
the same annual full distribution package by package and takes substantially longer.

```sh
docker build -f deploy/latex/Dockerfile -t polycolab-latex:local .
docker image inspect polycolab-latex:local --format '{{.Id}}'
```

Copy the resulting immutable `sha256:...` image ID into `LATEX_IMAGE` in
`deploy/docker/.env`. Set `LATEX_WORKER_TOKEN` to a separate random secret in that
same file. Both the API and compiler worker read these values; shell variables
override the file. Do not reuse agent credentials or put the token in a document.

Restart the local API or Docker stack so forward migrations and settings apply:

```sh
pnpm run dev:local
```

For the PostgreSQL/Garage stack use `pnpm run dev:docker` instead. In a separate
terminal start the compiler controller:

```sh
pnpm run api:latex-worker
```

The controller defaults to `http://127.0.0.1:8000`. Override with `LATEX_API_URL` or
`--api`. It uses the host Docker daemon, including Docker Desktop on macOS. No
Docker socket is mounted in the API or compilation containers. To use a second
slot, start another controller with `--worker-id latex-second`.

In Project → Worktree → Files, open or create a `.tex` file and select
**LaTeX / PDF preview**. Select the main file and pdfLaTeX or LuaLaTeX. Choose
**Compile** or **Save all & compile**. The latter saves all drafts in the current
worktree, including included files, without committing. A stale save preserves
drafts and prevents submission. Members can download results; only owners and
contributors can submit and cancel builds. PDFs and logs remain private even in
public projects. A failed build leaves the last successful PDF visible.

## Hosted deployment

Run the controller on a dedicated Linux account and rootless Docker daemon with
cgroup v2 and the systemd cgroup driver. Use a registry image pinned by digest
(`registry/name@sha256:...`) or the immutable local image ID. The build records
retain this image identity. Distribute the same image to every compiler host.

Install the backend's locked Python environment. Configure `LATEX_IMAGE`,
`LATEX_WORKER_TOKEN`, and `LATEX_API_URL` through a mode-0600 environment file for
the controller. Configure the matching image and token in the API. Use HTTPS
unless the API is on loopback. The controller needs no SQL or storage credential.
Install `polycolab-latex.service` after replacing its paths for the deployment.

The trusted supervisor is root **inside the container's user namespace** and
launches TeX as UID 65534. It retains only SETUID, SETGID, and KILL capabilities,
so the compiler cannot kill its watchdog. The image filesystem is read-only;
networking is disabled; no host directory is mounted. Source and output bytes
travel through bounded stdin/stdout. Scratch filesystems are bounded tmpfs. Source/output and temporary scratch are
non-executable; Biber has a separate 128 MiB executable tmpfs for its bundled Perl
interpreter and native libraries. This directory is private to each build and
contains no host mount or credential.
The supervisor kills compiler descendants before reading regular output files.
The controller confirms container removal before releasing a slot.

Do not treat a successful local compilation as hosted isolation acceptance.
Before enabling the hosted worker, verify cgroup limits, offline networking,
credential absence, timeout, cancellation, controller termination/restart, and
cleanup on the target daemon. Rootless preflight rejects unsupported cgroup
configuration. Host administrators still control image and daemon trust.

## Limits and recovery

Defaults are two running builds globally, one outstanding build per worktree,
ten outstanding builds per project, five minutes queue wait, two minutes execution,
one CPU, 1 GiB memory, 128 processes, 256 MiB work scratch, 16 MiB temporary
scratch, 128 MiB Biber scratch, 16 MiB PDF, and 1 MiB retained log. Source archives must fit the existing
16 MiB transfer limit. Per-project retained build storage is limited to 256 MiB.
API settings in `deploy/docker/.env.example` control admission and retention.

Workers renew readiness while idle and during compilation. No compatible ready
worker means new builds are disabled; historical results remain readable.
Controller startup removes only containers labelled for its API URL and worker
ID before advertising readiness. Use a stable, unique worker ID and preserve its
state directory. An exclusive local lock prevents duplicate controllers for that
ID. Lost leases fail explicitly; users request a new build rather than implicitly
retrying. Cancelled or lost builds retain physical capacity until confirmed
removal or their independent deadline plus a cleanup allowance.

PDFs/logs expire after 30 days. API maintenance deletes source archives after
terminal completion and a grace period, and deletes expired outputs. It never
writes build output into Git. Build metadata remains as a retry tombstone.
Disabling admission requires clearing `LATEX_IMAGE`; retain migrations and storage
while existing workers drain. Stop controllers after their containers are removed.

Shell escape, project latexmk configuration, and arbitrary build commands are
disabled. Packages that require external commands are not supported. Runtime
package downloads, automatic compilation, source/PDF synchronization, and external
agent build requests are not part of this release.

## Verification

The ordinary backend tests cover the API using real Git and SQLite. The mocked
browser journey covers editor behavior. For real container compilation with
pdfLaTeX/LuaLaTeX, TikZ and Biber, set the immutable local image ID:

```sh
POLYCOLAB_LATEX_IMAGE=sha256:<image-id> uv run --directory src/backend pytest ../../tests/backend/test_latex_execution.py -q
```

This test uses real containers and API/storage code with an in-process HTTP
transport and disposable SQLite/filesystem storage. It does not establish
PostgreSQL concurrency, Garage behavior, or hosted deployment acceptance.

For the real browser journey through separate API and worker processes, disposable
PostgreSQL and Garage, and real Docker compilation:

```sh
POLYCOLAB_LATEX_IMAGE=sha256:<image-id> uv run --directory src/backend python ../../tests/system/run_latex.py
```

This checks save-before-compile, rendered PDF pages, private downloads, persistence
across reload, diagnostics after failure, and cancellation. The browser uses Vite;
this is local integration evidence, not target-deployment acceptance. The runner
removes only its own containers, volumes, child processes, and temporary data.
