# Docker and gVisor executor

The native controller supports `gvisor` and `microsandbox` explicitly. There is no
fallback to ordinary Docker or to another backend. Core, PostgreSQL and object
storage remain in Compose. The controller accesses core through authenticated
HTTP and never receives database or provider credentials.

## Host preparation

Use Linux x86_64, cgroup v2, systemd, Python 3.14, and Docker with the systemd
cgroup driver. gVisor uses `systrap`; it does not require `/dev/kvm`. Keep the
application's Docker configuration intact when preparing a disposable test host.
A separate test daemon needs its own socket, data root, execution root and PID file.

1. Create a dedicated execution account and install the locked backend environment
   with `uv --directory src/backend sync --frozen`. The microsandbox extra is not
   required for this backend.
2. Install a verified, pinned runsc distribution in a root-owned directory. Keep
   its companion binaries with it. Record the distribution checksum, version and
   SHA-256 of the runsc binary. The example version is `release-20261005.0`.
3. Register this runtime in the chosen Docker daemon's configuration, merging with
   its existing settings. Restart that daemon only during an approved maintenance
   window:

   ```json
   {
     "exec-opts": ["native.cgroupdriver=systemd"],
     "runtimes": {
       "polycolab-runsc": {
         "path": "/opt/polycolab-runsc/runsc",
         "runtimeArgs": ["--platform=systrap", "--network=none"]
       }
     }
   }
   ```

4. Give the execution account access to this Docker socket. Docker socket access
   is host-level authority; the controller is trusted. The socket is never mounted
   into a guest.
5. Create account-owned mode-0700 `/var/lib/polycolab-execution`. Mount one separate
   finite filesystem of at most 4 GiB at `slots/0`, with `nodev,nosuid`. Set its
   root's owner to the execution account and mode to 0700. Start with capacity one.
   Each additional slot needs its own finite mount and memory budget. Reserve
   space outside the slots for images, core data and backups.
6. Install `polycolab/execution/docker_host.py` from the backend source as
   `/usr/local/libexec/polycolab-gvisor-host.py`. Install the wrapper
   `polycolab-gvisor-host` beside it, executable. Copy `gvisor-host.json.example`
   to `/etc/polycolab-execution/gvisor-host.json` and fill in the actual UID, socket,
   runtime paths and checksum. All three files and their parent directories must
   be root-owned and not writable by the execution account.
7. Using `visudo`, authorize only the fixed wrapper for the execution account:

   ```sudoers
   polycolab-execution ALL=(root) NOPASSWD: /usr/local/libexec/polycolab-gvisor-host
   ```

   The wrapper accepts `check`, or `prepare`, `verify`, `stop`, `release` with one
   attempt UUID. Its configuration path is fixed. It accepts no shell command.
   Do not grant sudo access to an account-writable Python module or configuration.

## Image and controller

Build [Dockerfile.agent](Dockerfile.agent) using an approved digest-pinned Node
base containing Python 3.11 or newer. It installs Codex 0.154.0 and the pinned guest
bridge. Push it to the approved registry and preload its exact `@sha256:` reference
into the selected daemon. Loading a tar archive alone may not preserve a repository
digest; preflight requires the exact reference in Docker's `RepoDigests`.
The controller never pulls an image during a run.

Copy [controller.gvisor.toml.example](controller.gvisor.toml.example) to the
controller configuration path. Register the accepted image:

```toml
[[images]]
reference = "REGISTRY/agent@sha256:MANIFEST_DIGEST"
language = "AGENT"
toolchain_version = "0.154.0"
dependency_lock_digest = "BUILD_LOCK_SHA256"
build_digest = "BUILD_RECIPE_SHA256"
platform_identity = "linux-x86_64"
```

Use real 64-character digests. Store the private runtime token in the account-owned
mode-0600 credential file outside the slots. Use HTTPS for a non-loopback core URL.
Run preflight as the execution account:

```sh
/opt/polycolab/src/backend/.venv/bin/python -m polycolab.execution.preflight \
  --config /etc/polycolab-execution/controller.toml
```

For the existing systemd user service, install this backend-specific drop-in:

```ini
[Service]
NoNewPrivileges=false
```

The controller must be able to invoke the restricted sudo helper. Guest containers
still enforce `no-new-privileges`, run as the non-root execution UID, drop all
capabilities, have a read-only root and read-only inputs, and have no networking.
All writable guest mounts use the same finite slot filesystem.

The helper creates an independent system-level deadline guard and a workload
slice. Before sending user work, it verifies that the runtime processes are inside
that slice with finite CPU, memory and process limits. The guard kills the slice
without relying on the Docker API. Cleanup confirms termination before deleting
outputs or returning the slot to the pool. Uncertain cleanup retains the journal
and quarantines the slot.

## Acceptance and rollout

Run native checks only against an idle disposable account/state directory:

```sh
POLYCOLAB_GVISOR_TEST_CONFIG=/etc/polycolab-execution/controller.toml \
  uv run --directory src/backend pytest ../../tests/execution/test_gvisor_native.py -v -s
```

These tests exercise actual Codex startup, offline networking, input/output transfer,
cleanup and the independent deadline. They do not establish live provider behavior
or production readiness. Complete the [failure acceptance gates](../../docs/architecture/hosted-failures.md)
before enabling production.

Drain existing controllers before applying the `20261013_executors` PostgreSQL
migration (`local_20261013_executors` for SQLite). Core and controller use private
protocol 5. Set `RUNTIME_SANDBOX_BACKEND=gvisor`, `RUNTIME_SANDBOX_VERSION` to the
accepted runsc version, `RUNTIME_CODEX_IMAGE` to the same digest, and
`HOSTED_AGENT_CAPACITY=1`. Configure object storage and then start the controller.
Existing frozen run specs retain their microsandbox identity. They are not
silently converted; matching backend, version and image are required to claim work.

Do not switch a state directory between backends while journals remain. Use a
separate state directory for each controller. On restart, reconcile retained
attempts before claiming. Never delete journals merely to clear quarantine.
For rollback, disable admission, drain or fence the executor, and retain the
forward-compatible database and historical records; do not downgrade the schema.
