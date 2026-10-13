# Linux hosted agents

The application and PostgreSQL remain in Compose.
A dedicated, unprivileged Linux account runs the hosted controller as a **systemd user service**.
Select the backend explicitly: [Docker/gVisor](gvisor.md), or microsandbox as described below.
Each microsandbox attempt runs in its own transient systemd unit and fresh offline VM.
The controller uses private APIs.
It has no database or provider credential.

The microsandbox installation steps remain **unverified**.
The image and native containment boundary still require acceptance.
Standalone Python/Lean verification remains disabled.

## Prepare the host

Use Ubuntu 24.04 x86_64 with working `/dev/kvm`, cgroup v2, systemd user services, and support for their filesystem isolation properties.
Prepare the execution account:

1. Create a dedicated `polycolab-execution` account.
2. Grant it access to KVM.
3. Enable its user manager with `loginctl enable-linger polycolab-execution`.
   Install the repository under `/opt/polycolab` and its locked environment:

```sh
uv --directory src/backend sync --extra execution --all-groups --frozen
```

Provision `/var/lib/polycolab-execution` as an account-owned mode-0700 directory.
For each slot (default four), mount a **separate finite filesystem of at most 4 GiB** at `slots/0` through `slots/3`.
Assign each mount's root to the execution account.
Set its mode to 0700.
Use persistent mounts with `nodev,nosuid`.
Do not use directories on an unbounded host filesystem.

The slot contains SDK state, image cache, guest disk, outputs and temporary files.
Budget enough host memory for four 1 GiB VMs plus four 512 MiB executor allowances and the application.
Reducing capacity is supported in both API settings and controller configuration.

Build `Dockerfile.agent` from an approved digest-pinned Node/glibc base containing Python 3.
The Dockerfile pins Codex CLI 0.154.0.
Record the resulting OCI manifest digest, base digest, architecture, and build evidence.
Export an OCI/Docker archive.
An image tag is insufficient.
Audit the image for privilege-changing binaries and unnecessary services before acceptance.

Prepare the controller configuration:

1. Copy `controller.toml.example` to `/etc/polycolab-execution/controller.toml`.
2. Configure the immutable image policy.
3. Create an account-owned mode-0600 `agent-token` matching the API's private runtime worker token.
   This credential stays outside all slot filesystems.
   Do not put provider keys or database settings in the host configuration.
   Use HTTPS for a non-loopback API URL.

As the execution account, run this command to load the image in every slot.
The command also verifies the image:

```sh
/opt/polycolab/src/backend/.venv/bin/python -m polycolab.execution.preflight \
  --config /etc/polycolab-execution/controller.toml --archive /absolute/agent.tar
```

Omit `--archive` for subsequent read-only checks.
Preflight checks KVM, cgroup v2, private bounded mounts, user-manager access, SDK version and cached image identity.
It does not prove VM isolation or real Codex compatibility.

## Acceptance and enablement

On the disposable target, test the actual transient unit and VM before enabling production.
Record SDK 0.6.18 and Codex 0.154.0 versions and image identity alongside results for:

- Offline guest networking, read-only inputs and inaccessible service credentials.
- CPU, memory, process, wall-time and disk exhaustion.
  Bounded host logs and outputs.
- Cancellation, controller SIGKILL/restart, ambiguous creation and stop, and orphan reconciliation.
  Confirm no process remains before physical slot reuse.
- Real app-server startup, Responses forwarding with a user-owned profile, research tools, completed chat, follow-up turns and reconnect from a browser.
- Four simultaneous attempts across users/projects, queue fairness, stale lease rejection and conservative provider settlement after lease loss.
- Explicit artifact downloads and cross-user denial.
  No retained raw commands, reasoning, undeclared project files or automatic publication.

Install the unit in the account's `~/.config/systemd/user/`.
Run `systemctl --user daemon-reload`.
Start it only for the accepted deployment:

```sh
systemctl --user start polycolab-execution.service
```

After acceptance, configure the API:

1. Set `RUNTIME_CODEX_IMAGE` to the same digest.
2. Configure artifact storage before enabling agent execution.
3. Set capacity as appropriate: `HOSTED_AGENT_CAPACITY=4`, `HOSTED_AGENT_USER_CAPACITY=2`, and `HOSTED_AGENT_PROJECT_CAPACITY=2`.

The controller advertises readiness every ten seconds, expiring after 45 seconds.
New hosted work requires a matching live executor.
Historical sessions remain readable when none is available.
Users select a validated **Responses** profile in Sessions.
Existing chat-completions profiles need replacement or reconfiguration.

Ordinary run/provider failures affect one chat.
Unconfirmed cleanup quarantines its slot.
Healthy slots continue.
Host-wide authority, identity or containment failures stop the controller.

Restart stops journaled attempts, confirms exact generations through the API, and then claims on healthy slots.
Do not delete journals to clear quarantine.
Repair the slot.
Restart the controller so reconciliation proves cleanup.

Controller incarnations expire after 45 seconds, so a restart can wait for the previous readiness advertisement to expire.
Systemd enforces attempt deadlines even if the controller dies.
The allocator reserves an additional 30 seconds for cleanup.
Do not remove the legacy Compose worker until native and browser acceptance passes.
Legacy workers cannot claim runs with a hosted Codex runtime specification.

## Recovery service and rollout

Apply migrations through `20261013_executors` before starting the new API and controller. The API owns the recovery background job.
Drain the old controller before upgrading.
New hosted claims require private protocol version 6 and an explicit physical slot.

The reconciler shares the core application database pool.
It polls every five seconds; keep core running when executor admission is disabled.
The reconciler needs no extra provider or controller credential.

A run that may have dispatched a provider request or changed research requires explicit user resume after runner loss.
Resume creates a new run.
Review prior work before resuming.
External effects do not have an exactly-once execution guarantee.
The default deadline remains 300 seconds from admission, including queue time.

For rollback, stop new admissions.
Drain or fence controllers.
Keep the API, its background jobs, and historical data available.
Do not downgrade away completion receipts or delete quarantined reservations.
See the [failure acceptance matrix](../../docs/architecture/hosted-failures.md).

Docker-free development uses forward SQLite migrations through `local_20261013_executors`.
Existing local accounts, research and uploads are retained, with a pre-upgrade backup.
Hosted VMs still require the separate Linux host.
The PostgreSQL merge revision preserves both previous migration histories and supports upgrading from either `20260915_submission_numbers` or `20260915_hosted_recovery`.

## Project repository checkout

Rebuild the curated agent image with Git and the guest repository helper before
using protocol 6. Successful file outputs are saved as uncommitted changes in the
canonical worktree for human review. Keep Codex state in `/home/agent/.codex`, outside `/workspace`.
The API alone mounts the persistent repository volume. Hosted slots receive a
bounded bundle for an exact commit, clone it into `/workspace`, and export their
task working-copy branch on successful completion. They never mount the canonical volume.
See [project files](../../docs/architecture/project-files.md) for limits,
branch ownership, backup, and recovery. The legacy Compose worker does not execute
repository-enabled sessions.

Native acceptance must cover a real pinned image: clone, shell edit, successful
checkpoint, fresh-run restore, cancellation, controller restart, revoked access,
and cleanup of the finite slot filesystem. Local transport and helper tests do
not establish these Linux VM properties.
